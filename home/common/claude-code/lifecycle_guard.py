"""Claude Code's PreToolUse Bash lifecycle guard.

The claude-code module's store wrapper clears NIX_PYTHON* and runs this file
under `python3 -I` with `--policy <store JSON of the Nix-owned values>`.
Standard library only: it imports nothing from the repository's helper package.
"""

import argparse
import json
import os
import re
import shlex
import subprocess
import sys


POLICY_KEYS = frozenset(
    {"authorized_owners", "integration_bases", "git_bin", "gh_bin", "jq_bin"}
)
CHILD_DIAGNOSTIC_LIMIT = 240
# The harness exports a fine-grained GITHUB_TOKEN that gh prefers over the
# keyring credential, and its reach is narrower — it cannot see every
# authorized owner's org. The guard's forge lookups drop the env tokens so
# validation observes GitHub with the keyring credential, the same auth
# the `unset GITHUB_TOKEN && ` form of the guarded command will use. A
# machine with no keyring auth still fails closed at the lookup.
GH_ENV_TOKEN_NAMES = ("GITHUB_TOKEN", "GH_TOKEN")
# A resolved exhaustive credential-name list may yield the concrete command
# `unset GITHUB_TOKEN && gh ...`. The merge grammar accepts that one literal prefix and
# nothing looser; the remainder must still match the guarded merge argv in
# full, so nothing else can ride along.
UNSET_GITHUB_TOKEN_PREFIX = "unset GITHUB_TOKEN && "
# The guarded verbs, as raw text and as token sequences. Order matters: the
# first match at a token wins, and no sequence is a prefix of another.
GUARDED_LITERALS = (
    ("gh pr merge", "merge"),
    ("gh pr create", "pr-create"),
    ("git branch -d", "branch"),
    ("git push", "push"),
    ("gh release create", "release"),
    # `new` is gh's alias of `create`; it routes to the same grammar, which
    # refuses it because the grammar spells `create`.
    ("gh release new", "release"),
)
GUARDED_TOKEN_LITERALS = (
    (["gh", "pr", "merge"], "merge"),
    (["gh", "pr", "create"], "pr-create"),
    (["git", "branch", "-d"], "branch"),
    (["git", "push"], "push"),
    (["gh", "release", "create"], "release"),
    (["gh", "release", "new"], "release"),
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
# Programs whose argument is shell source. Arbitrary shell cannot be parsed
# here, so a guarded verb anywhere in such a segment is refused outright, and
# so is a detaching word (matched there as raw text, including when the
# evaluator is named by path, as in `/bin/sh -c`).
SHELL_EVALUATORS = frozenset({"eval", "sh", "bash", "zsh", "dash", "ksh"})
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
PR_CREATE_FLAGS = ("--repo", "--base", "--head", "--title", "--body")
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
    """Per token: does a simple command start here?"""
    flags = [False] * len(tokens)
    open_position = True
    wrapper = None
    for index, (value, operator) in enumerate(tokens):
        if operator:
            open_position = True
            wrapper = None
            continue
        if not open_position:
            continue
        if ASSIGNMENT_PREFIX.match(value) is not None:
            continue
        if value in COMMAND_KEYWORDS or value in COMMAND_WRAPPERS:
            wrapper = value
            continue
        if wrapper is not None and value.startswith("-"):
            # Options belonging to the wrapper (`env -i`, `sudo -u anis`).
            continue
        flags[index] = True
        open_position = False
    return flags


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


def unvalidatable(segment, reason, mentions_label=False):
    """Every guarded verb mentioned in `segment`, all refused for `reason`.

    When `mentions_label` is set, the raise-label edit is refused too.
    """
    found = [
        (operation, segment, reason)
        for literal, operation in GUARDED_LITERALS
        if literal in segment
    ]
    if mentions_label:
        found.append(("label", segment, reason))
    return found


def guarded_operations(command):
    """(operation, segment, problem) for every guarded verb the shell would run.

    `problem` is None when the segment can be handed to that verb's grammar,
    and a reason when the verb sits where the guard cannot validate it: an
    unparseable command, shell source passed to `eval`/`sh -c`, or a position
    that is not a command position (an argument to some other program). Those
    are refused rather than waved through — the parser and the shell have to
    agree, and where they cannot the guard fails closed.

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
    for segment in segments:
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
        flags = command_position_flags(tokens)
        values = [value for value, _ in tokens]
        mentions = mentions_raise_label(values)
        if any(
            flag and value in SHELL_EVALUATORS
            for flag, value in zip(flags, values)
        ):
            found.extend(unvalidatable(
                segment, "shell source passed to an evaluator cannot be validated",
                mentions,
            ))
            continue
        for index in range(len(values)):
            for literal_tokens, operation in GUARDED_TOKEN_LITERALS:
                if values[index:index + len(literal_tokens)] != literal_tokens:
                    continue
                if flags[index]:
                    found.append((operation, segment, None))
                else:
                    found.append((
                        operation,
                        segment,
                        "the verb is not in a command position the guard can "
                        "validate; quote it if you only mean to mention it",
                    ))
                break
    # Judged over every tokenised segment at once: a separator inside a
    # substitution (`gh pr edit $(gh pr view | jq …) --add-label …`) splits
    # the `gh` word from its label, so a per-segment check would miss it.
    if mentions_raise_label([value for value, _ in stream]) and adds_raise_label(stream):
        found.append(("label", command, RAISE_LABEL_REFUSAL))
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
        ))
    return found


# Wrapper options that consume an argument, so the word holding it is not the
# wrapped command. Used only by the detaching pass. Short options may be
# clustered (`env -iu FOO`), and an argument may be attached (`-uanis`,
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

    Like `command_position_flags`, but it also steps over redirections, attached
    (`nohup>log`) or not, and over the arguments of wrapper options, so
    `>log nohup x` and `sudo -u anis nohup x` are seen. An operator token ends
    any pending option argument. The verb pass keeps `command_position_flags`;
    this pass has no such fail-closed backstop, hence the extra stepping.
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


class Policy:
    """The Nix-owned values, read from the store policy file."""

    def __init__(self, document):
        self.authorized_owners = frozenset(document["authorized_owners"])
        self.integration_bases = dict(document["integration_bases"])
        self.git_bin = document["git_bin"]
        self.gh_bin = document["gh_bin"]
        self.jq_bin = document["jq_bin"]


def load_policy(path):
    """(Policy, None) for a well-formed policy file at `path`, else (None, reason)."""
    try:
        with open(path, encoding="utf-8") as handle:
            document = json.load(handle)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        return None, f"cannot load {path}: {error}"
    if not isinstance(document, dict) or set(document) != POLICY_KEYS:
        keys = ", ".join(sorted(POLICY_KEYS))
        return None, f"{path}: expected an object with exactly the keys {keys}"
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
    return Policy(document), None


class Context:
    """Injected dependencies plus the repository facts, resolved once."""

    def __init__(self, args, policy, cwd):
        self.git_bin = args.git_bin
        self.gh_bin = args.gh_bin
        self.jq_bin = args.jq_bin
        self.timeout = args.child_timeout_seconds
        self.authorized_owners = policy.authorized_owners
        self.integration_bases = policy.integration_bases
        self.repository = detect_repository(self.git_bin, cwd, self.timeout)
        self.base_branch = default_branch(self.git_bin, cwd, self.timeout)
        self.cwd = cwd


def ownership_problem(repository, authorized_owners):
    """Why `repository` is outside standing authorization, or None."""
    if repository is None:
        return "repository unknown is outside standing authorization"
    if repository.split("/", 1)[0] not in authorized_owners:
        return f"repository {repository} is outside standing authorization"
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
    """Why `branch` is not a plain, safe branch name, or None."""
    if not branch:
        return "branch name must not be empty"
    if branch.startswith("-"):
        return "branch must not begin with a dash"
    if ":" in branch or "+" in branch:
        return "refspecs and force-pushes are not authorized"
    if any(character in UNSAFE_BRANCH_CHARS for character in branch):
        return "forbidden branch character"
    if any(component in REF_NAMESPACE_COMPONENTS for component in branch.split("/")):
        # `refs/heads/main` and `heads/main` both name the branch `main`, so a
        # plain string comparison against the default branch would miss them.
        return "namespaced refs are not authorized, name the branch directly"
    try:
        child = subprocess.run(
            [git_bin, "check-ref-format", "--branch", branch],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return "branch validation timed out"
    if child.returncode != 0:
        return "invalid branch name"
    return None


def free_text_problem(value, allow_newlines):
    """Why `value` is not safe to hand to the shell verbatim, or None."""
    if not value:
        return "must not be empty"
    forbidden = set(UNSAFE_TEXT_CHARS)
    if not allow_newlines:
        forbidden.add("\n")
    if any(character in forbidden for character in value):
        return "contains a forbidden character"
    if any(0xD800 <= ord(character) <= 0xDFFF for character in value):
        return "contains an unpaired surrogate"
    return None


def parse_merge_raw(command, repository):
    """The guarded merge as (number, subject, delete_branch), or None.

    Two arms share one spelling. The feature arm ends in `--delete-branch`:
    a feature branch is disposable once merged. The release arm omits it,
    because there the head is the declared integration branch, which is
    permanent; `validate_merge` confines that arm to exactly that PR shape.
    """
    prefix = "gh pr merge "
    if not command.startswith(prefix):
        return None

    number, separator, remainder = command[len(prefix):].partition(" ")
    if (
        not separator
        or not number
        or any(character < "0" or character > "9" for character in number)
        or int(number) <= 0
    ):
        return None

    delete_branch_suffix = " --delete-branch"
    delete_branch = remainder.endswith(delete_branch_suffix)
    if delete_branch:
        remainder = remainder[:-len(delete_branch_suffix)]

    if remainder == f"--repo {repository} --merge":
        return number, None, delete_branch

    subject_prefix = f'--repo {repository} --merge --subject "'
    subject_suffix = '"'
    if not remainder.startswith(subject_prefix) or not remainder.endswith(subject_suffix):
        return None

    subject = remainder[len(subject_prefix):-len(subject_suffix)]
    if free_text_problem(subject, False) is not None:
        return None
    return number, subject, delete_branch


def validate_branch_delete(command, git_bin, timeout):
    """Branch deletion is guarded in every repository, ownership aside."""
    if any(character in UNSAFE_BRANCH_CHARS for character in command):
        return block("unsafe branch deletion: forbidden raw command character")
    try:
        command_argv = shlex.split(command)
    except ValueError as error:
        return block(f"unsafe branch deletion: invalid command quoting: {error}")
    if len(command_argv) != 4 or command_argv[:3] != ["git", "branch", "-d"]:
        return block("unsafe branch deletion: expected exactly git branch -d <branch>")
    branch = command_argv[3]
    if branch.startswith("-"):
        return block("unsafe branch deletion: branch must not begin with a dash")
    try:
        ref_check = subprocess.run(
            [git_bin, "check-ref-format", "--branch", branch],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return block("unsafe branch deletion: branch validation timed out")
    if ref_check.returncode != 0:
        return block("unsafe branch deletion: invalid branch name")
    return 0


def validate_tag_push(tag, context):
    """The tag-push arm: `git push origin refs/tags/<vX.Y.Z>` of an existing annotated tag.

    The caller has judged the owner and the raw characters. The tag must exist
    locally as an annotated tag object (`git cat-file -t` prints `tag`), so a
    lightweight tag, a missing one or a branch of the same name never passes.
    """
    if SEMVER_TAG.fullmatch(tag) is None:
        return block("unsafe push: a tag push must name a vMAJOR.MINOR.PATCH tag")
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
        return block("unsafe push: tag lookup timed out")
    if kind.returncode != 0 or kind.stdout.strip() != "tag":
        return block(f"unsafe push: {tag} is not an existing annotated tag")
    return 0


def validate_push(segment, context):
    problem = ownership_problem(context.repository, context.authorized_owners)
    if problem is not None:
        return block(f"unsafe push: {problem}")
    if any(character in UNSAFE_BRANCH_CHARS for character in segment):
        return block("unsafe push: forbidden raw command character")
    try:
        command_argv = shlex.split(segment)
    except ValueError as error:
        return block(f"unsafe push: invalid command quoting: {error}")
    if (
        len(command_argv) == 4
        and command_argv[:3] == ["git", "push", "origin"]
        and command_argv[3].startswith(TAG_REF_PREFIX)
    ):
        return validate_tag_push(command_argv[3][len(TAG_REF_PREFIX):], context)
    if len(command_argv) == 5 and command_argv[:4] == ["git", "push", "-u", "origin"]:
        branch = command_argv[4]
    elif len(command_argv) == 4 and command_argv[:3] == ["git", "push", "origin"]:
        branch = command_argv[3]
    else:
        return block("unsafe push: expected exactly git push [-u] origin <branch>")
    reason = branch_name_problem(context.git_bin, branch, context.timeout)
    if reason is not None:
        return block(f"unsafe push: {reason}")
    if context.base_branch is None:
        return block("unsafe push: cannot resolve the repository default branch")
    if branch == context.base_branch:
        return block(f"unsafe push: refusing to push the default branch {branch}")
    return 0


def validate_pr_create(segment, context):
    problem = ownership_problem(context.repository, context.authorized_owners)
    if problem is not None:
        return block(f"unsafe PR creation: {problem}")
    try:
        command_argv = shlex.split(segment)
    except ValueError as error:
        return block(f"unsafe PR creation: invalid command quoting: {error}")
    if len(command_argv) != 13 or command_argv[:3] != ["gh", "pr", "create"]:
        return block(
            "unsafe PR creation: expected exactly gh pr create --repo <repo> "
            "--base <base> --head <head> --title <title> --body <body>"
        )
    if tuple(command_argv[3::2]) != PR_CREATE_FLAGS:
        return block(
            "unsafe PR creation: flags must be --repo --base --head --title --body in order"
        )
    repository_argument, base, head, title, body = command_argv[4::2]
    if repository_argument != context.repository:
        return block(
            f"unsafe PR creation: --repo {repository_argument} is not the "
            f"current repository {context.repository}"
        )
    reason = branch_name_problem(context.git_bin, head, context.timeout)
    if reason is not None:
        return block(f"unsafe PR creation: head {reason}")
    for name, value, allow_newlines in (("title", title, False), ("body", body, True)):
        text_problem = free_text_problem(value, allow_newlines)
        if text_problem is not None:
            return block(f"unsafe PR creation: {name} {text_problem}")
    if context.base_branch is None:
        return block("unsafe PR creation: cannot resolve the repository default branch")
    allowed_bases = authorized_bases(
        context.repository, context.base_branch, context.integration_bases
    )
    if base not in allowed_bases:
        return block(
            "unsafe PR creation: --base must be one of "
            + ", ".join(sorted(allowed_bases))
        )
    if head == base:
        return block("unsafe PR creation: head and base must differ")
    return 0


def parse_release_raw(command, repository):
    """The guarded release creation as (tag, title, notes_path), or None.

    The one spelling is `gh release create <tag> --repo <repository>
    --verify-tag --title "<title>" --notes-file <path>`: no `--target`, no
    draft or prerelease flags, nothing before or after.
    """
    prefix = "gh release create "
    if not command.startswith(prefix):
        return None
    tag, separator, remainder = command[len(prefix):].partition(" ")
    if not separator or SEMVER_TAG.fullmatch(tag) is None:
        return None
    title_prefix = f'--repo {repository} --verify-tag --title "'
    if not remainder.startswith(title_prefix):
        return None
    title, quote_found, path = remainder[len(title_prefix):].rpartition('" --notes-file ')
    if not quote_found or free_text_problem(title, False) is not None:
        return None
    if (
        not os.path.isabs(path)
        or any(character in UNSAFE_BRANCH_CHARS or character.isspace() for character in path)
    ):
        return None
    return tag, title, path


def validate_release(command, context):
    """Release creation is judged on the whole command, like the merge."""
    problem = ownership_problem(context.repository, context.authorized_owners)
    if problem is not None:
        return block(f"unsafe release creation: {problem}")
    if command.startswith(UNSET_GITHUB_TOKEN_PREFIX):
        command = command[len(UNSET_GITHUB_TOKEN_PREFIX):]
    parts = parse_release_raw(command, context.repository)
    if parts is None:
        return block(
            "unsafe release creation: command does not match the guarded release grammar"
        )
    tag, title, path = parts
    try:
        command_argv = shlex.split(command)
    except ValueError as error:
        return block(f"unsafe release creation: invalid command quoting: {error}")
    expected_argv = [
        "gh", "release", "create", tag, "--repo", context.repository,
        "--verify-tag", "--title", title, "--notes-file", path,
    ]
    if command_argv != expected_argv:
        return block("unsafe release creation: tokenised command does not match guarded argv")
    return 0


def validate_merge(command, context):
    problem = ownership_problem(context.repository, context.authorized_owners)
    if problem is not None:
        return block(f"unsafe merge: {problem}")
    repository = context.repository
    # The one sanctioned prefix is derived from a resolved exhaustive
    # credential-name list and is `unset GITHUB_TOKEN && gh pr merge ...`.
    # Strip exactly that
    # literal and judge the remainder as the whole command, so the merge
    # still tolerates no other chaining.
    if command.startswith(UNSET_GITHUB_TOKEN_PREFIX):
        command = command[len(UNSET_GITHUB_TOKEN_PREFIX):]
    merge_parts = parse_merge_raw(command, repository)
    if merge_parts is None:
        return block("unsafe merge: command does not match the guarded merge grammar")
    number, subject, delete_branch = merge_parts
    try:
        command_argv = shlex.split(command)
    except ValueError as error:
        return block(f"unsafe merge: invalid command quoting: {error}")
    expected_argv = [
        "gh", "pr", "merge", number, "--repo", repository, "--merge",
    ]
    if subject is not None:
        expected_argv.extend(["--subject", subject])
    if delete_branch:
        expected_argv.append("--delete-branch")
    if command_argv != expected_argv:
        return block("unsafe merge: tokenised command does not match guarded argv")
    if context.base_branch is None:
        return block("unsafe merge: cannot resolve the repository default branch")
    allowed_bases = authorized_bases(
        repository, context.base_branch, context.integration_bases
    )
    integration_base = context.integration_bases.get(repository)

    # The release arm — no `--delete-branch` — exists for one PR shape
    # only: the declared integration branch promoted into the default
    # branch, whose head must survive the merge. Where no such branch is
    # declared there is nothing to spare, so refuse before any lookup.
    if not delete_branch and integration_base is None:
        return block(
            "unsafe merge: --delete-branch may be omitted only in a repository "
            "with a declared integration branch"
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
        return block("unsafe merge: cannot read the PR base branch")
    if base not in allowed_bases:
        return block(f"unsafe merge: PR base {base} is not an authorized base")

    if not delete_branch:
        return validate_release_merge(pr_facts, base, integration_base, context)

    # The feature arm deletes the PR's head branch, so the head must be
    # disposable: never the default branch, never the declared integration
    # branch (#116 D5). Judged before any protection lookup.
    head = pr_facts.get("headRefName")
    if not isinstance(head, str) or not head:
        return block("unsafe merge: cannot read the PR head branch")
    if head in (context.base_branch, integration_base):
        return block(
            f"unsafe merge: --delete-branch would delete the permanent branch {head}"
        )

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


def validate_release_merge(pr_facts, base, integration_base, context):
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
        return block("unsafe merge: cannot read the PR head branch")
    if head != integration_base or base != context.base_branch:
        return block(
            "unsafe merge: --delete-branch may be omitted only when merging "
            f"{integration_base} into {context.base_branch}; this PR merges "
            f"{head} into {base}"
        )
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
    parser = argparse.ArgumentParser(prog="claude-bash-lifecycle-guard")
    parser.add_argument("--policy", required=True)
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

    policy, reason = load_policy(args.policy)
    if policy is None:
        return block(f"invalid policy: {reason}")
    if args.git_bin is None:
        args.git_bin = policy.git_bin
    if args.gh_bin is None:
        args.gh_bin = policy.gh_bin
    if args.jq_bin is None:
        args.jq_bin = policy.jq_bin

    operations = guarded_operations(command)
    for operation, _segment, problem in operations:
        if operation == "label":
            return block(f"unsafe {OPERATION_LABELS[operation]}: {problem}")

    context = None
    for operation, segment, problem in operations:
        if problem is not None:
            return block(f"unsafe {OPERATION_LABELS[operation]}: {problem}")
        if operation == "branch":
            # Branch deletion is judged on the whole command, in every
            # repository: it needs no forge state and tolerates no chaining.
            status = validate_branch_delete(
                command, args.git_bin, args.child_timeout_seconds
            )
        else:
            if context is None:
                context = Context(args, policy, payload.get("cwd"))
            if operation == "push":
                status = validate_push(segment, context)
            elif operation == "pr-create":
                status = validate_pr_create(segment, context)
            elif operation == "release":
                status = validate_release(command, context)
            else:
                status = validate_merge(command, context)
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
