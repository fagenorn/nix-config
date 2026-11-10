"""Owner actions (issue 624): which GitHub repositories this machine's checkouts belong to.

Source entry `python -m agent_tools.claims.owner_actions`. The module keeps a per-repository count of the
open issues and pull requests that wait on the owner, so a Claude Code status line can show it
without a network call. An item needs you (counted in `count`) when it carries the `owner-action`
label or the `agent:human-required` label; an item is answered and waiting (counted in `answered`,
issue 670) when it carries `owner-answered` and neither of those, so no item is in both. The
`in-progress` label and every other label never count, an item carrying none of the three is
ignored, and a closed item never counts. The one search asks for
`label:owner-action,agent:human-required,owner-answered`.

P1: a checkout's `origin` is read by decoding `.git/config` in-process with git's own syntax
(quoting, comments, continuations, case rules), because a regular expression over the text
accepts what git would reject and rejects what git would accept.
P2: identity never starts a process, so the statusline can ask it on every render at no cost.
P3: one cache file per repository, `<state>/owner-actions/<owner>/<name>.json`, written atomically
as bytes through `agent_platform.write_atomically` as `{"schema_version": 2, "repo", "count",
"oldest", "answered"}`; its mtime is the age of the data, an entry that does not parse to exactly
that shape (a `schema_version` 1 entry included) reads as absent so the next statusline call
schedules a refresh, and deleting it loses nothing because the next refresh rebuilds it.
P4: an item's time is the latest `LabeledEvent` of each counted label it carries, minimum over those
labels; a repository's `oldest` is the minimum over its needs-you items, kept as the server's own
timestamp string; an answered item has no age.
P4b: a refresh publishes only a complete answer: the search is followed page by page through its
cursor, and a truncated label or label-event connection on an item, a search unfinished after
`MAX_PAGES` (ten), or one that returned fewer nodes than its `issueCount` (GitHub caps a search at
1,000 results) fails that repository with `payload_incomplete` and writes nothing. Page flags,
counts and timestamps must be well formed (an offset-bearing ISO 8601 instant, `Z` included) or the
refresh fails `payload_invalid`; a cache entry with a malformed `oldest` reads as missing.
P5: items are counted by their current labels, whatever the server returned: an item carrying
`owner-action` or `agent:human-required` is needs-you (`count`, with its age), an item carrying
`owner-answered` and neither of those is answered-and-waiting (`answered`, no age), never both, and an
item carrying none of the three is ignored.
P6: the first page also reads the `owner-action` label (not `owner-answered`), and a missing one is
created with color `D93F0B`.
`refresh [--repo <owner/name>]` runs one GraphQL search per repository through `gh` and
rewrites that repository's cache entry; without `--repo` it takes every slug in the project registry
and attempts each of them even after one fails. It prints one JSON line `{"refreshed": [<slug>...],
"failed": [{"repo": <slug>, "error": <code>}...]}` on stdout and one `owner-actions: <slug>: <error>`
line per failure on stderr (an unreadable registry is reported as `owner-actions: registry: ...` with
`"repo": null`); it exits 0 when nothing failed and 1 otherwise.
P7: a statusline starts a refresh only by holding an exclusive `flock` on `<name>.refresh`, which also
records the last attempt's time; the child inherits the locked descriptor and so holds the claim until
it exits, and attempts are spaced `RETRY_AFTER` (120 s) apart whatever their outcome. An entry is
stale when it is absent or its file is more than `STALE_AFTER` (15 minutes) old; a stale call prints
the cached value at once and starts at most one detached refresh, spawning only when no refresh holds
the lock and the recorded attempt is old enough. The claim file is never deleted or truncated by
anyone but the next claimant. A failure to claim or spawn is one stderr line, `owner-actions: refresh
claim for <slug> failed: ...` or `owner-actions: refresh spawn for <slug> failed: ...`, and the cached
value is still printed with exit 0.
P8: the detached child is `sibling_argv("claims.owner_actions") + ["refresh", "--repo", slug]` in its own
session with `cwd` `/`, its output going to `<name>.log`.
`statusline` reads the Claude Code status-line JSON on stdin, takes `cwd` (or
`workspace.current_dir` when `cwd` is absent or not a string), reads that checkout's `origin` slug
from its git config files without running `git`, and prints the cached value for it only when the
slug belongs to a registered project's checkout. It prints `owner <count> (oldest <days>d)` (days
rounded down, never negative) or `owner <count>` when no label time is known, followed by `, answered
<answered>` when `answered` is above 0; `answered <answered>` alone when `count` is 0 and `answered`
is above 0; and nothing when both are 0 or no entry exists; it never runs `gh`.
P10: a statusline prints nothing for the expected blank cases (input that is not a JSON object, a
missing or non-string directory, a directory outside a GitHub checkout, a repository outside the
fleet; nothing on stderr, exit 0) and lets every other failure escape to `main`, which reports the
traceback on stderr, prints nothing on stdout and exits 1; a corrupt registry is one of those.
"""

import argparse
import fcntl
import json
import os
import re
import subprocess
import sys
import time
import traceback
from collections.abc import Iterator
from datetime import datetime
from pathlib import Path
from typing import Any

from agent_tools.project_contract import agent_platform
from agent_tools.claims import forge_claim
from agent_tools.system import forge_api, siblings
from agent_tools.system.github_remote import github_slug

# A repository name may begin with a dot (`org/.github`) but is never `.` or `..`; an owner never does.
SLUG_PATTERN = re.compile(r"[A-Za-z0-9_-][A-Za-z0-9_.-]*/(?!\.{1,2}$)[A-Za-z0-9_.-]+")

COUNTED = ("owner-action", "agent:human-required")
ANSWERED = "owner-answered"
SCHEMA_VERSION = 2
MAX_PAGES = 10
STALE_AFTER = 900
RETRY_AFTER = 120

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
    issueCount
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
            "-f", f"search=repo:{slug} is:open label:{','.join((*COUNTED, ANSWERED))}",
            *(["-f", f"after={after}"] if after else [])]


def cache_path(slug: str) -> Path:
    owner, name = slug.split("/", 1)
    return agent_platform.state_root() / "owner-actions" / owner / f"{name}.json"


def _instant(text: str) -> datetime:
    """`text` as an offset-bearing ISO 8601 instant, or ValueError."""
    moment = datetime.fromisoformat(text)
    if moment.tzinfo is None:
        raise ValueError(f"timestamp without an offset: {text!r}")
    return moment


def read_entry(slug: str) -> dict | None:
    """The cache entry for `slug` when it parses and has exactly the expected shape, else None."""
    try:
        entry = json.loads(cache_path(slug).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(entry, dict) or set(entry) != {"schema_version", "repo", "count", "oldest", "answered"}:
        return None
    count, answered = entry["count"], entry["answered"]
    if (entry["schema_version"] != SCHEMA_VERSION or entry["repo"] != slug
            or isinstance(count, bool) or not isinstance(count, int) or count < 0
            or isinstance(answered, bool) or not isinstance(answered, int) or answered < 0
            or not (entry["oldest"] is None or isinstance(entry["oldest"], str))):
        return None
    if entry["oldest"] is not None:
        try:
            _instant(entry["oldest"])
        except ValueError:
            return None
    return entry


def write_entry(slug: str, count: int, oldest: str | None, answered: int = 0) -> None:
    entry = {"schema_version": SCHEMA_VERSION, "repo": slug, "count": count, "oldest": oldest,
             "answered": answered}
    agent_platform.write_atomically(
        cache_path(slug), (json.dumps(entry, sort_keys=True) + "\n").encode("utf-8"))


def claim_path(slug: str) -> Path:
    return cache_path(slug).with_suffix(".refresh")


def log_path(slug: str) -> Path:
    return cache_path(slug).with_suffix(".log")


def render(entry: dict | None, now: float) -> str:
    """The status-line text for a cache entry, without a newline; `""` when there is nothing to say."""
    if entry is None:
        return ""
    parts = []
    if entry["count"] > 0:
        if entry["oldest"] is None:
            parts.append(f"owner {entry['count']}")
        else:
            days = max(0, int((now - _instant(entry["oldest"]).timestamp()) // 86400))
            parts.append(f"owner {entry['count']} (oldest {days}d)")
    if entry["answered"] > 0:
        parts.append(f"answered {entry['answered']}")
    return ", ".join(parts)


def claim_refresh(slug: str, now: float) -> int | None:
    """A descriptor holding the claim's exclusive lock when the caller should spawn, else None (P7)."""
    path = claim_path(slug)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o600)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            os.close(fd)
            return None
        try:
            last = float(os.read(fd, 64).decode("utf-8", "replace").strip())
        except ValueError:
            last = None
        if last is not None and 0 <= now - last < RETRY_AFTER:
            os.close(fd)
            return None
        os.lseek(fd, 0, os.SEEK_SET)
        os.ftruncate(fd, 0)
        os.write(fd, f"{now:.3f}\n".encode("ascii"))
        return fd
    except BaseException:
        try:
            os.close(fd)
        except OSError:
            pass
        raise


def spawn_refresh(slug: str, claim_fd: int) -> None:
    """Start the detached child that refreshes `slug` and holds the claim until it exits (P8)."""
    with open(log_path(slug), "wb") as log:
        subprocess.Popen(siblings.sibling_argv("claims.owner_actions") + ["refresh", "--repo", slug],
                         stdin=subprocess.DEVNULL, stdout=log, stderr=log, start_new_session=True,
                         cwd="/", pass_fds=(claim_fd,))


def _cwd(payload: Any) -> str | None:
    if not isinstance(payload, dict):
        return None
    if isinstance(payload.get("cwd"), str):
        return payload["cwd"]
    workspace = payload.get("workspace")
    if isinstance(workspace, dict) and isinstance(workspace.get("current_dir"), str):
        return workspace["current_dir"]
    return None


def statusline(stdin_text: str) -> str:
    """Everything `statusline` prints; expected blank cases return `""`, other failures raise (P10)."""
    try:
        payload = json.loads(stdin_text)
    except ValueError:
        return ""
    cwd = _cwd(payload)
    if cwd is None:
        return ""
    slug = checkout_slug(cwd)
    if slug is None or slug not in fleet_slugs():
        return ""
    now = time.time()
    entry = read_entry(slug)
    stale = entry is None
    if not stale:
        try:
            stale = now - cache_path(slug).stat().st_mtime > STALE_AFTER
        except FileNotFoundError:
            stale = True
    if stale:
        try:
            fd = claim_refresh(slug, now)
        except OSError as error:
            print(f"owner-actions: refresh claim for {slug} failed: {error}", file=sys.stderr)
        else:
            if fd is not None:
                try:
                    spawn_refresh(slug, fd)
                except OSError as error:
                    print(f"owner-actions: refresh spawn for {slug} failed: {error}", file=sys.stderr)
                finally:
                    os.close(fd)
    text = render(read_entry(slug), now)
    return text + "\n" if text else ""


def _invalid(detail: str) -> forge_api.ForgeError:
    return forge_api.ForgeError("payload_invalid", detail)


def _total(connection: dict, what: str, field: str = "totalCount") -> int:
    total = connection.get(field)
    if isinstance(total, bool) or not isinstance(total, int) or total < 0:
        raise _invalid(f"{what}.{field} is not a non-negative integer")
    return total


def _connection(node: dict, field: str) -> tuple[dict, list]:
    connection = node.get(field)
    if not isinstance(connection, dict) or not isinstance(connection.get("nodes"), list):
        raise _invalid(f"search node {field} is not a connection")
    return connection, connection["nodes"]


def _page(data: Any) -> tuple[list, dict, int]:
    """The nodes, pageInfo and issueCount of one search answer."""
    search = data.get("data", {}).get("search") if isinstance(data, dict) and isinstance(
        data.get("data"), dict) else None
    if (not isinstance(search, dict) or not isinstance(search.get("nodes"), list)
            or not isinstance(search.get("pageInfo"), dict)):
        raise _invalid("search page has an unexpected shape")
    if not isinstance(search["pageInfo"].get("hasNextPage"), bool):
        raise _invalid("search pageInfo.hasNextPage is not a boolean")
    return search["nodes"], search["pageInfo"], _total(search, "search", "issueCount")


def _item(node: dict) -> tuple[str | None, str | None]:
    """The search node's class (P5: "needs", "answered" or None) and its time (P4), or raise when truncated."""
    labels, label_nodes = _connection(node, "labels")
    if _total(labels, "labels") > len(label_nodes):
        raise forge_api.ForgeError("payload_incomplete", "an item's labels are truncated")
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
                try:
                    _instant(event["createdAt"])
                except ValueError:
                    raise _invalid(f"label event createdAt is not an ISO 8601 instant: "
                                   f"{event['createdAt']!r}") from None
                latest = event["createdAt"]
        if latest is not None:
            times.append(latest)
        elif total > len(events):
            raise forge_api.ForgeError(
                "payload_incomplete", "an item's label events are truncated")
    kind = "needs" if names & set(COUNTED) else "answered" if ANSWERED in names else None
    return kind, min(times, key=_instant) if times else None


def refresh(slug: str) -> dict:
    """Count the open owner-only items of `slug` and write the cache entry; raises ForgeError."""
    nodes: list = []
    label_missing = False
    issue_count = 0
    cursor: str | None = None
    seen: set[str] = set()
    for page in range(1, MAX_PAGES + 1):
        data = forge_api.gh_json(search_argv(slug, cursor))
        page_nodes, info, issue_count = _page(data)
        nodes.extend(page_nodes)
        if page == 1:
            repository = data["data"].get("repository")
            label_missing = isinstance(repository, dict) and repository.get("label") is None
        if not info["hasNextPage"]:
            break
        cursor = info.get("endCursor")
        if not isinstance(cursor, str) or not cursor or cursor in seen:
            raise _invalid("search page has a missing or repeated endCursor")
        seen.add(cursor)
        if page == MAX_PAGES:
            raise forge_api.ForgeError(
                "payload_incomplete", f"search still has pages after {MAX_PAGES}")
    if len(nodes) < issue_count:
        raise forge_api.ForgeError(
            "payload_incomplete", f"search returned {len(nodes)} of {issue_count} matches")
    count = answered = 0
    oldest: str | None = None
    for node in nodes:
        if not isinstance(node, dict):
            continue
        kind, time = _item(node)
        if kind == "answered":
            answered += 1
        if kind != "needs":
            continue
        count += 1
        if time is not None and (oldest is None or _instant(time) < _instant(oldest)):
            oldest = time
    if label_missing:
        forge_api.ensure_label(slug, *forge_claim.OWNER_ACTION)
    write_entry(slug, count, oldest, answered)
    return {"schema_version": SCHEMA_VERSION, "repo": slug, "count": count, "oldest": oldest,
            "answered": answered}


def _slug(text: str) -> str:
    if not SLUG_PATTERN.fullmatch(text):
        raise argparse.ArgumentTypeError(f"not an owner/name slug: {text!r}")
    return text


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="owner-actions")
    commands = parser.add_subparsers(dest="command", required=True)
    refreshing = commands.add_parser("refresh", help="refresh the cached owner-action counts")
    refreshing.add_argument("--repo", type=_slug, help="one owner/name slug; default is the fleet")
    commands.add_parser("statusline", help="print the cwd repository's owner actions from the cache")
    args = parser.parse_args(argv)
    if args.command == "statusline":
        try:
            text = statusline(sys.stdin.read())
        except Exception:
            traceback.print_exc()
            return 1
        sys.stdout.write(text)
        return 0
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
        except forge_api.ForgeError as error:
            failed.append({"repo": slug, "error": error.code})
            print(f"owner-actions: {slug}: {error}", file=sys.stderr)
        except OSError as error:
            failed.append({"repo": slug, "error": "cache_write"})
            print(f"owner-actions: {slug}: cache_write: {error}", file=sys.stderr)
        else:
            refreshed.append(slug)
    print(json.dumps({"refreshed": refreshed, "failed": failed}, sort_keys=True))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
