"""Owner actions (issue 624): which GitHub repositories this machine's checkouts belong to.

P1: a checkout's `origin` is read by decoding `.git/config` in-process with git's own syntax
(quoting, comments, continuations, case rules), because a regular expression over the text
accepts what git would reject and rejects what git would accept.
P2: identity never starts a process, so the statusline can ask it on every render at no cost.
"""

import os
import re
from collections.abc import Iterator
from pathlib import Path

from agent_tools import agent_platform
from agent_tools.github_remote import github_slug

SLUG_PATTERN = re.compile(r"[A-Za-z0-9_-][A-Za-z0-9_.-]*/[A-Za-z0-9_-][A-Za-z0-9_.-]*")

_KEY = re.compile(r"[A-Za-z][A-Za-z0-9-]*")
_SECTION_NAME = re.compile(r"[A-Za-z0-9.-]+")
_BLANK = " \t"
_ESCAPES = {'"': '"', "\\": "\\", "n": "\n", "t": "\t", "b": "\b"}


def _git_dir(start: Path) -> Path | None:
    """The git dir of the checkout containing `start`: the first `.git` found walking upward."""
    here = Path(start).resolve()
    if here.is_file():
        here = here.parent
    for directory in (here, *here.parents):
        dot_git = directory / ".git"
        if dot_git.is_dir():
            return dot_git
        if dot_git.is_file():
            first = dot_git.read_text(encoding="utf-8").split("\n", 1)[0].strip()
            if not first.startswith("gitdir:"):
                return None
            return Path(directory, first[len("gitdir:"):].strip())
        if os.path.lexists(dot_git):
            return None
    return None


def _config_path(git_dir: Path) -> Path:
    """`<git_dir>/config`, or the common dir's config for a linked worktree."""
    common = git_dir / "commondir"
    if common.is_file():
        return Path(git_dir, common.read_text(encoding="utf-8").strip()) / "config"
    return git_dir / "config"


def _header(text: str, i: int) -> tuple[str, str | None, int]:
    """Decode the header whose `[` is at `text[i - 1]`: (section, subsection, index after `]`)."""
    n = len(text)
    while i < n and text[i] in _BLANK:
        i += 1
    named = _SECTION_NAME.match(text, i)
    if named is None:
        raise ValueError("section header without a name")
    name, i = named.group(), named.end()
    sub: str | None = None
    while i < n and text[i] in _BLANK:
        i += 1
    if i < n and text[i] == '"':
        i += 1
        chars: list[str] = []
        while True:
            if i >= n or text[i] == "\n":
                raise ValueError("unterminated subsection quote")
            c = text[i]
            if c == '"':
                i += 1
                break
            if c == "\\":
                i += 1
                if i >= n or text[i] == "\n":
                    raise ValueError("unterminated subsection escape")
                c = text[i]
            chars.append(c)
            i += 1
        sub = "".join(chars)
    elif "." in name:
        name, sub = name.split(".", 1)
        sub = sub.lower()
    while i < n and text[i] in _BLANK:
        i += 1
    if i >= n or text[i] != "]":
        raise ValueError("unterminated section header")
    return name.lower(), sub, i + 1


def _value(text: str, i: int) -> tuple[str, int]:
    """Decode a value starting at `text[i]` up to its unquoted end of line: (value, index after)."""
    n = len(text)
    while i < n and text[i] in _BLANK:
        i += 1
    out: list[str] = []
    keep = 0
    quoted = False
    while i < n:
        c = text[i]
        if c == "\n":
            break
        if c == '"':
            quoted = not quoted
        elif c == "\\":
            i += 1
            if i >= n:
                raise ValueError("backslash at end of file")
            e = text[i]
            if e == "\n":
                i += 1
                continue
            if e not in _ESCAPES:
                raise ValueError(f"unknown escape \\{e}")
            out.append(_ESCAPES[e])
            keep = len(out)
        elif not quoted and c in "#;":
            while i < n and text[i] != "\n":
                i += 1
            break
        else:
            out.append(c)
            if quoted or c not in _BLANK:
                keep = len(out)
        i += 1
    if quoted:
        raise ValueError("unterminated quote")
    return "".join(out[:keep]), i


def _config_entries(text: str) -> Iterator[tuple[str, str | None, str, str | None]]:
    """Yield `(section_lower, subsection, key_lower, value_or_None)` per git-config syntax.

    Raises ValueError on a malformed file.
    """
    text = text.replace("\r\n", "\n")
    n = len(text)
    i = 0
    section: str | None = None
    sub: str | None = None
    while i < n:
        c = text[i]
        if c in " \t\n":
            i += 1
        elif c in "#;":
            while i < n and text[i] != "\n":
                i += 1
        elif c == "[":
            section, sub, i = _header(text, i + 1)
        else:
            key = _KEY.match(text, i)
            if key is None or section is None:
                raise ValueError("expected a variable name")
            i = key.end()
            while i < n and text[i] in _BLANK:
                i += 1
            if i >= n or text[i] == "\n":
                yield section, sub, key.group().lower(), None
            elif text[i] in "#;":
                while i < n and text[i] != "\n":
                    i += 1
                yield section, sub, key.group().lower(), None
            elif text[i] == "=":
                value, i = _value(text, i + 1)
                yield section, sub, key.group().lower(), value
            else:
                raise ValueError("expected `=` after a variable name")


def _origin_url(config: Path) -> str | None:
    """The first `url` of `remote "origin"` in `config`, else None."""
    for section, sub, key, value in _config_entries(config.read_text(encoding="utf-8")):
        if (section, sub, key) == ("remote", "origin", "url") and value is not None:
            return value
    return None


def checkout_slug(path: str | os.PathLike) -> str | None:
    """The GitHub `owner/name` of `origin` for the checkout containing `path`, or None."""
    try:
        git_dir = _git_dir(Path(path))
        if git_dir is None:
            return None
        url = _origin_url(_config_path(git_dir))
        slug = None if url is None else github_slug(url)
        return slug if slug is not None and SLUG_PATTERN.fullmatch(slug) else None
    except (OSError, UnicodeDecodeError, ValueError):
        return None


def fleet_slugs() -> frozenset[str]:
    """The slugs of every registered project's checkout; unresolvable entries are skipped."""
    return frozenset(s for e in agent_platform.read_registry()
                     if (s := checkout_slug(e["root"])) is not None)
