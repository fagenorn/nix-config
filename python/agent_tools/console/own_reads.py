"""The own-read rule: plain reads a manager's session may run without a permission card (#1620, ADR-console-103).

A manager's `PermissionRequest` hook (`sprint permit --prompt`) raises the owner's card for every Bash
command the client would ask about. A manager reading its own saved tool output, or a file of its own
worktree, with `sed`, `head`, `tail`, `cat`, `grep` or `wc` costs the owner a card for nothing. `allowed`
is the rule that removes exactly those cards: it is pure over the command, the hook's working directory,
the session id, the trusted root and the transcript stores, and every refusal falls through to the card
the owner answers. It never raises: any `OSError`, `ValueError`, `RecursionError` or `TypeError` is False.

What it admits: one command of the literal-word grammar (`permit.words`: no operator, redirection, pipe,
chain, substitution, glob or tilde), whose first word is bare `sed`, `head`, `tail`, `cat`, `grep` or
`wc` (`PROGRAMS`; never `/bin/cat`, `env cat` or `FOO=1 cat`), every file operand of which resolves to a
path inside the trusted root or inside the session's own `tool-results` directory.

The grammar (`operands`). Words are read in an option phase and then a positional phase that starts at
the first word not beginning with `-`; any word beginning with `-` in the positional phase refuses,
because under `POSIXLY_CORRECT` GNU tools stop option parsing at the first operand and would open it as
a file. In the option phase `--`, a lone `-` and any `--long` word refuse, and each option is on its
program's list:

- `cat`: `-n`, `-b`, `-s`. `wc`: a cluster of `lwcm`.
- `head`: `-n` or `-c` with a following number, or attached (`-n5`), or `-5`. `tail` the same, the
  number optionally `+`-led (`-n +3`); never `-f`, `-F` or `-r`.
- `grep`: a cluster of `inclLvwxFEoHhsq`; `-m`, `-A`, `-B`, `-C` with a number (following or attached);
  `-e <pattern>` any number of times. Without `-e` the first positional is the pattern, not a path.
- `sed`: exactly `sed -n <script> <path>...` with a script of one line number or `$`, or two joined by a
  comma, then `p`. No `-i`, `-e`, `-E`, `-f` and no script that writes.

At least one path operand is required.

The path rule. Each operand is resolved by `resolve`, a physical walk of `os.path.join(cwd, operand)` in
the hook (no `~` expansion): one component at a time with `os.lstat`, a link's target spliced in front of
the rest, `..` popping the resolved prefix after links as the kernel does, more than 40 links refused, a
missing or non-directory middle component refused, a missing last component returned as spelled. A path
component, a link target's included, on the device of `/proc` refuses: a process-relative link
(`/proc/self/cwd`, `/proc/self/fd/N`, and `/dev/fd/N`, a link into `/proc` on Linux) resolves in the hook to a
different object than in the utility. `/dev` itself is not barred: `/dev/shm`, where a scratch directory
may live, is under it, and a device node there lies outside the root and refuses as a non-file.
The resolved path must lie inside the real path of `root` (`project_question_hook._inside`,
spelling then identity, so a case alias of the root is the root) or inside the session's own saved output
(`project_question_hook.session_results`, genuine directories only). An operand that resolves to a
regular file with more than one link refuses: a hard link could name a file outside the root. An operand
that exists and is neither a regular file nor a directory (a named pipe, socket or device) refuses. `cwd` must
be an absolute string, `session` a string matching `SESSION_NAME`, and `root` counts only when it is an
absolute string (else only the session's own output passes).

`grep` refuses when `GREP_OPTIONS` is in the environment: BSD grep prepends it to its arguments, so the
command text no longer shows every file grep opens.
"""

from __future__ import annotations

import os
import re
import stat
from collections.abc import Mapping, Sequence

from agent_tools.console import permit, project_question_hook

PROGRAMS: tuple[str, ...] = ("sed", "head", "tail", "cat", "grep", "wc")

_SED_SCRIPT = re.compile(r"(?:[0-9]+|\$)(?:,(?:[0-9]+|\$))?p")
_CAT_OPTIONS = frozenset({"-n", "-b", "-s"})
_WC_OPTION = re.compile(r"-[lwcm]+")
_GREP_BOOLEANS = re.compile(r"-[inclLvwxFEoHhsq]+")
_GREP_NUMBERED = re.compile(r"-[mABC][0-9]+")
_NUMBER = re.compile(r"[0-9]+")
_TAIL_NUMBER = re.compile(r"\+?[0-9]+")
_MAX_LINKS = 40


def _count_option(word: str, following: str | None, value: re.Pattern[str]) -> int | None:
    """The words a `head` or `tail` option takes (1 or 2), or None when `word` is not one of its options."""
    if word in ("-n", "-c"):
        return 2 if following is not None and value.fullmatch(following) else None
    if re.fullmatch(r"-[nc]", word[:2]) and value.fullmatch(word[2:]):
        return 1
    return 1 if _NUMBER.fullmatch(word[1:]) else None


def _option(program: str, word: str, following: str | None) -> tuple[int, bool] | None:
    """`(words taken, whether the option gave grep its pattern)` for an option word, or None when refused."""
    if word == "-" or word.startswith("--"):
        return None
    if program == "cat":
        return (1, False) if word in _CAT_OPTIONS else None
    if program == "wc":
        return (1, False) if _WC_OPTION.fullmatch(word) else None
    if program in ("head", "tail"):
        taken = _count_option(word, following, _NUMBER if program == "head" else _TAIL_NUMBER)
        return None if taken is None else (taken, False)
    if program == "grep":
        if _GREP_BOOLEANS.fullmatch(word) or _GREP_NUMBERED.fullmatch(word):
            return 1, False
        if word in ("-m", "-A", "-B", "-C"):
            return (2, False) if following is not None and _NUMBER.fullmatch(following) else None
        if word == "-e":
            return (2, True) if following is not None else None
    return None


def _parse(command: str) -> tuple[str, list[str]] | None:
    """`(program, path operands)` of a command in the grammar, or None."""
    found = permit.words(command)
    if not found or found[0] not in PROGRAMS:
        return None
    program, args = found[0], found[1:]
    if program == "sed":
        if len(args) < 3 or args[0] != "-n" or not _SED_SCRIPT.fullmatch(args[1]):
            return None
        paths, start, pattern = args[2:], 2, True
    else:
        start, pattern = 0, False
        while start < len(args) and args[start].startswith("-"):
            following = args[start + 1] if start + 1 < len(args) else None
            taken = _option(program, args[start], following)
            if taken is None:
                return None
            start += taken[0]
            pattern = pattern or taken[1]
        paths = args[start:]
        if program == "grep" and not pattern:
            paths = paths[1:]
    if not paths or any(word.startswith("-") for word in args[start:]):
        return None
    return program, paths


def operands(command: str) -> list[str] | None:
    """The path operands of a command in the grammar, None for anything else."""
    parsed = _parse(command)
    return None if parsed is None else parsed[1]


def _barred_devices() -> frozenset[int]:
    """The device of `/proc`, the process-relative file system, where it exists."""
    found = set()
    for name in ("/proc",):
        try:
            found.add(os.stat(name).st_dev)
        except (FileNotFoundError, NotADirectoryError):
            pass
    return frozenset(found)


def _components(path: str) -> list[str]:
    """The components of `path`, last first, so `pop()` takes the next to walk."""
    return path.split("/")[::-1]


def resolve(cwd: str, operand: str) -> str | None:
    """The physical resolution of `os.path.join(cwd, operand)`, or None where it refuses.

    A walk, one component at a time with `os.lstat`; see the module docstring for the rule.
    """
    barred = _barred_devices()
    path = os.path.join(cwd, operand)
    pending = _components(path)
    done: list[str] = []
    links = 0
    while pending:
        part = pending.pop()
        if part in ("", "."):
            continue
        if part == "..":
            if done:
                done.pop()
            continue
        current = "/" + "/".join(done + [part])
        try:
            status = os.lstat(current)
        except FileNotFoundError:
            return None if any(rest not in ("", ".") for rest in pending) else current
        except NotADirectoryError:
            return None
        if status.st_dev in barred:
            return None
        if stat.S_ISLNK(status.st_mode):
            links += 1
            if links > _MAX_LINKS:
                return None
            target = os.readlink(current)
            if target.startswith("/"):
                done = []
            pending.extend(_components(target))
            continue
        if not stat.S_ISDIR(status.st_mode) and pending:
            return None
        done.append(part)
    return "/" + "/".join(done)


def _may_read(path: str, root: str | None, session: str, stores: Sequence[str]) -> bool:
    """Whether the resolved `path` is a single-link file or directory inside the root or the session's output.

    A named pipe, socket or device refuses: a read could block on a writer or consume another process's stream."""
    try:
        status = os.stat(path)
    except (FileNotFoundError, NotADirectoryError):
        pass
    else:
        if not (stat.S_ISREG(status.st_mode) or stat.S_ISDIR(status.st_mode)) or (
                stat.S_ISREG(status.st_mode) and status.st_nlink > 1):
            return False
    if root is not None and project_question_hook._inside(path, root):
        return True
    return project_question_hook.session_results(path, session, stores)


def allowed(command: str, cwd: object, session: object, root: object, stores: Sequence[str],
            environ: Mapping[str, str]) -> bool:
    """Whether `command` is a plain read of the root's or the session's own saved files; never raises."""
    try:
        if not isinstance(cwd, str) or not os.path.isabs(cwd):
            return False
        if not isinstance(session, str) or not project_question_hook.SESSION_NAME.fullmatch(session):
            return False
        parsed = _parse(command)
        if parsed is None or (parsed[0] == "grep" and "GREP_OPTIONS" in environ):
            return False
        real_root = os.path.realpath(root) if isinstance(root, str) and os.path.isabs(root) else None
        for operand in parsed[1]:
            resolved = resolve(cwd, operand)
            if resolved is None or not _may_read(resolved, real_root, session, stores):
                return False
        return True
    except (OSError, ValueError, RecursionError, TypeError):
        return False
