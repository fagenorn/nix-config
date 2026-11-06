"""Owner actions (issue 624): which GitHub repositories this machine's checkouts belong to.

P1: a checkout's `origin` is read by decoding `.git/config` in-process with git's own syntax
(quoting, comments, continuations, case rules), because a regular expression over the text
accepts what git would reject and rejects what git would accept.
P2: identity never starts a process, so the statusline can ask it on every render at no cost.
P3: one cache file per repository, `<state>/owner-actions/<owner>/<name>.json`, written as bytes
through `agent_platform.write_atomically`; its mtime is the staleness, and deleting it loses nothing.
P4: an item's time is the latest `LabeledEvent` of each counted label it carries, minimum over those
labels; a repository's `oldest` is the minimum over its items, kept as the server's own string.
P4b: a refresh publishes only a complete answer: the search is followed page by page, and a truncated
per-item connection or a search unfinished after `MAX_PAGES` fails the refresh and writes nothing.
P5: items are counted by their current labels, whatever the server returned.
P6: the first page also reads the `owner-action` label, and a missing one is created.
"""

import argparse
import json
import os
import re
import sys
from collections.abc import Iterator
from datetime import datetime
from pathlib import Path
from typing import Any

from agent_tools import agent_platform, forge_claim, forge_markers
from agent_tools.github_remote import github_slug

SLUG_PATTERN = re.compile(r"[A-Za-z0-9_-][A-Za-z0-9_.-]*/[A-Za-z0-9_-][A-Za-z0-9_.-]*")

COUNTED = ("owner-action", "agent:human-required")
SCHEMA_VERSION = 1
MAX_PAGES = 10

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


QUERY = """query($owner: String!, $name: String!, $search: String!, $after: String) {
  repository(owner: $owner, name: $name) { label(name: "owner-action") { name } }
  search(query: $search, type: ISSUE, first: 100, after: $after) {
    pageInfo { hasNextPage endCursor }
    nodes {
      ... on Issue {
        labels(first: 100) { totalCount nodes { name } }
        timelineItems(itemTypes: [LABELED_EVENT], last: 100) { totalCount nodes { ... on LabeledEvent { createdAt label { name } } } }
      }
      ... on PullRequest {
        labels(first: 100) { totalCount nodes { name } }
        timelineItems(itemTypes: [LABELED_EVENT], last: 100) { totalCount nodes { ... on LabeledEvent { createdAt label { name } } } }
      }
    }
  }
}"""


def search_argv(slug: str, after: str | None = None) -> list[str]:
    owner, name = slug.split("/", 1)
    return ["api", "graphql", "-f", f"query={QUERY}", "-f", f"owner={owner}", "-f", f"name={name}",
            "-f", f"search=repo:{slug} is:open label:{','.join(COUNTED)}",
            *(["-f", f"after={after}"] if after else [])]


def cache_path(slug: str) -> Path:
    owner, name = slug.split("/", 1)
    return agent_platform.state_root() / "owner-actions" / owner / f"{name}.json"


def read_entry(slug: str) -> dict | None:
    """The cache entry for `slug` when it parses and has exactly the expected shape, else None."""
    try:
        entry = json.loads(cache_path(slug).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(entry, dict) or set(entry) != {"schema_version", "repo", "count", "oldest"}:
        return None
    count = entry["count"]
    if (entry["schema_version"] != SCHEMA_VERSION or entry["repo"] != slug
            or isinstance(count, bool) or not isinstance(count, int) or count < 0
            or not (entry["oldest"] is None or isinstance(entry["oldest"], str))):
        return None
    return entry


def write_entry(slug: str, count: int, oldest: str | None) -> None:
    entry = {"schema_version": SCHEMA_VERSION, "repo": slug, "count": count, "oldest": oldest}
    agent_platform.write_atomically(
        cache_path(slug), (json.dumps(entry, sort_keys=True) + "\n").encode("utf-8"))


def _invalid(detail: str) -> forge_markers.ForgeError:
    return forge_markers.ForgeError("payload_invalid", detail)


def _total(connection: dict, what: str) -> int:
    total = connection.get("totalCount")
    if isinstance(total, bool) or not isinstance(total, int):
        raise _invalid(f"{what}.totalCount is not an integer")
    return total


def _connection(node: dict, field: str) -> tuple[dict, list]:
    connection = node.get(field)
    if not isinstance(connection, dict) or not isinstance(connection.get("nodes"), list):
        raise _invalid(f"search node {field} is not a connection")
    return connection, connection["nodes"]


def _page(data: Any) -> tuple[list, dict]:
    """The nodes and pageInfo of one search answer."""
    search = data.get("data", {}).get("search") if isinstance(data, dict) and isinstance(
        data.get("data"), dict) else None
    if (not isinstance(search, dict) or not isinstance(search.get("nodes"), list)
            or not isinstance(search.get("pageInfo"), dict)):
        raise _invalid("search page has an unexpected shape")
    return search["nodes"], search["pageInfo"]


def _item(node: dict) -> tuple[bool, str | None]:
    """Whether the search node carries a counted label, and its time (P4), or raise when truncated."""
    labels, label_nodes = _connection(node, "labels")
    if _total(labels, "labels") > len(label_nodes):
        raise forge_markers.ForgeError("payload_incomplete", "an item's labels are truncated")
    timeline, events = _connection(node, "timelineItems")
    total = _total(timeline, "timelineItems")
    names = {n.get("name") for n in label_nodes if isinstance(n, dict)}
    times: list[str] = []
    for counted in (c for c in COUNTED if c in names):
        latest = None
        for event in events:
            if not isinstance(event, dict) or not isinstance(event.get("createdAt"), str):
                continue
            label = event.get("label")
            if isinstance(label, dict) and label.get("name") == counted:
                latest = event["createdAt"]
        if latest is not None:
            times.append(latest)
        elif total > len(events):
            raise forge_markers.ForgeError(
                "payload_incomplete", "an item's label events are truncated")
    return bool(names & set(COUNTED)), min(times, key=datetime.fromisoformat) if times else None


def refresh(slug: str) -> dict:
    """Count the open owner-only items of `slug` and write the cache entry; raises ForgeError."""
    nodes: list = []
    label_missing = False
    cursor: str | None = None
    seen: set[str] = set()
    for page in range(1, MAX_PAGES + 1):
        data = forge_markers._json(search_argv(slug, cursor))
        page_nodes, info = _page(data)
        nodes.extend(page_nodes)
        if page == 1:
            repository = data["data"].get("repository")
            label_missing = isinstance(repository, dict) and repository.get("label") is None
        if info.get("hasNextPage") is not True:
            break
        cursor = info.get("endCursor")
        if not isinstance(cursor, str) or not cursor or cursor in seen:
            raise _invalid("search page has a missing or repeated endCursor")
        seen.add(cursor)
        if page == MAX_PAGES:
            raise forge_markers.ForgeError(
                "payload_incomplete", f"search still has pages after {MAX_PAGES}")
    count = 0
    oldest: str | None = None
    for node in nodes:
        if not isinstance(node, dict):
            continue
        counted, time = _item(node)
        if not counted:
            continue
        count += 1
        if time is not None and (oldest is None
                                 or datetime.fromisoformat(time) < datetime.fromisoformat(oldest)):
            oldest = time
    if label_missing:
        forge_markers.ensure_label(slug, *forge_claim.OWNER_ACTION)
    write_entry(slug, count, oldest)
    return {"schema_version": SCHEMA_VERSION, "repo": slug, "count": count, "oldest": oldest}


def _slug(text: str) -> str:
    if not SLUG_PATTERN.fullmatch(text):
        raise argparse.ArgumentTypeError(f"not an owner/name slug: {text!r}")
    return text


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="owner-actions")
    commands = parser.add_subparsers(dest="command", required=True)
    refreshing = commands.add_parser("refresh", help="refresh the cached owner-action counts")
    refreshing.add_argument("--repo", type=_slug, help="one owner/name slug; default is the fleet")
    args = parser.parse_args(argv)
    refreshed: list[str] = []
    failed: list[dict] = []
    if args.repo is not None:
        slugs = [args.repo]
    else:
        try:
            slugs = sorted(fleet_slugs())
        except agent_platform.PlatformManifestError as error:
            slugs = []
            failed.append({"repo": None, "error": "registry"})
            print(f"owner-actions: registry: {error}", file=sys.stderr)
    for slug in slugs:
        try:
            refresh(slug)
        except forge_markers.ForgeError as error:
            failed.append({"repo": slug, "error": error.code})
            print(f"owner-actions: {slug}: {error}", file=sys.stderr)
        else:
            refreshed.append(slug)
    print(json.dumps({"refreshed": refreshed, "failed": failed}, sort_keys=True))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
