"""`look_check`: the verify script that an approved look raises no owner-review card (#1186, AC5).

`python -m agent_tools.console.look_check --repo OWNER/NAME --since SHA [--url BASE]` finds the
first marked issue that landed under an approved look after this host activated the change, and
reports whether the console, once it had read the tracker after the issue was held, shows no
owner-review card for it. It reads `/run/current-system`, so it runs on the console host.

Usage. `--since` is the 40-hex merge commit of the change; `--url` defaults to
`http://127.0.0.1:27184` and only `http` with host `127.0.0.1` or `localhost` is accepted. Anything
else is a usage error.

Boundary. Times are parsed with `datetime.fromisoformat(s.replace("Z", "+00:00"))`; an unparseable
time is treated as missing. T is `commit.committer.date` of the `--since` commit and A the time of the
first activation of a system that carried the change on this host: A is the `st_mtime` of
`lstat("/run/current-system")` (replaced by every activation and boot) the first time this check runs
for `--since`, written once to `$HOME/.agents/state/verify-pending/look-check-activation-<since>` and read
back on every later run, so a later switch or reboot never moves it (verify-pending runs the check only
once the system contains the change, so the first run follows its first activation). Without `HOME` or when
the file cannot be written or read, A is the current `st_mtime`. The boundary is B = max(T, A). When the
current `st_mtime` is unknown the check exits 75 `activation_unknown` without listing pulls.

Landing. Closed pulls are read page by page (`sort=updated&direction=desc&per_page=100&page=k`,
k = 1, 2, ...), stopping after a page of fewer than 100 items or one whose last item was updated
before B (a pull merged at or after B was updated at or after B, so every such pull sorts before
that item). A pull is a candidate when its `merged_at` is not before B and its head sha is 40
lowercase hex; candidates are judged in ascending `(merged_at, number)`. A candidate's issues are
the numbers on its body lines `Refs #N` or `Closes #N`, ascending. An issue qualifies when its body
carries a look marker (`look_marker.read_look`) and `look_marker.look_answer` of its comments for
`(issue, pull, head)` is `approved`. A qualifying closed issue is passed over; an open one without
`needs-verification` ends the run 75 `not_held`; an open held one is the landing, held at the
`created_at` of its latest `labeled` event naming that label, and no later candidate is read. With no
landing the check exits 75 `waiting` and does not read the console.

Console. The state is read from `<url>/api/state` (5 second timeout). A console that does not answer
200 with a JSON object is 75 `not_running`. The project is every project entry, in `entries` or in a
`quiet_group`'s `projects`, whose `slug_of(root)` equals the repository case-insensitively; none is
75 `not_registered`. A fresh read is a `tracker_read` that is `ok` with `began_at` (the time the read
started, before it fetched anything; the console sets it, `read_at` is its finish time) not before
max(hold time, merge time of the landing): a missing read or a missing, unparseable or earlier
`began_at` is 75 `not_read`, a failed one 75 `stale`. With a fresh read, the offending keys are the
sorted `key` of the open inbox items of that repository and issue whose kind is `owner-review` and whose
`criterion` is one of the issue's look-marker criteria (the checkbox lines of its acceptance criteria
whose line is one of `look_marker.marker_lines`, the look-marker lines `tick` ticks; a card of an ordinary `[human]` criterion never counts): any is
1 `not_met` with `keys`, none is 0 `met`. Every not-yet and verdict line carries `issue` and `pr` once there is a landing.

Output and exits: one JSON line with sorted keys; the only file written is the activation record. 0 met, 1 not met, 75 not yet,
2 a usage error, a forge error or a malformed forge answer (`{"status": "error", "detail"}`). The
seams of `main` are `get`, `comments`, `state`, `activated_at`, `fixed_activation` and `slug_of`.
"""
import argparse
import http.client
import json
import os
import re
import sys
from collections.abc import Callable, Mapping
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlsplit

from agent_tools.claims import forge_markers, owner_actions
from agent_tools.console import inbox
from agent_tools.delivery import look_marker
from agent_tools.system import forge_api
from agent_tools.system.forge_api import ForgeError

DEFAULT_URL = "http://127.0.0.1:27184"
LOOPBACK = ("127.0.0.1", "localhost")
STATE_PATH = "/api/state"
STATE_TIMEOUT = 5.0
ACTIVATION_LINK = "/run/current-system"
RECORD_DIR = ".agents/state/verify-pending"
RECORD_PREFIX = "look-check-activation-"
HELD_LABEL = "needs-verification"
REVIEW_KIND = "owner-review"
PAGE = 100
NOT_YET = 75
CLOSES = re.compile(r"^(?:Refs|Closes) #(\d+)\s*$", re.MULTILINE)

Get = Callable[[str], Any]


class Usage(Exception):
    pass


class _Parser(argparse.ArgumentParser):
    def error(self, message):
        raise Usage(message)


def parse_time(text: Any) -> datetime | None:
    if not isinstance(text, str):
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=timezone.utc)


def default_state(url: str) -> dict | None:
    parts = urlsplit(url)
    connection = http.client.HTTPConnection(parts.hostname, parts.port, timeout=STATE_TIMEOUT)
    try:
        connection.request("GET", STATE_PATH)
        response = connection.getresponse()
        body = response.read()
        document = json.loads(body) if response.status == 200 else None
    except (OSError, http.client.HTTPException, ValueError):
        return None
    finally:
        connection.close()
    return document if isinstance(document, dict) else None


def default_activated_at() -> datetime | None:
    try:
        return datetime.fromtimestamp(os.lstat(ACTIVATION_LINK).st_mtime, timezone.utc)
    except OSError:
        return None


def default_fixed_activation(since: str, current: datetime) -> datetime:
    """The first activation recorded for `since`; the current one, written once, when none is."""
    home = os.environ.get("HOME")
    if not home:
        return current
    path = os.path.join(home, RECORD_DIR, RECORD_PREFIX + since)
    try:
        with open(path, encoding="utf-8") as handle:
            recorded = parse_time(handle.read().strip())
        if recorded is not None:
            return recorded
    except FileNotFoundError:
        pass
    except OSError:
        return current
    try:
        os.makedirs(os.path.dirname(path), mode=0o700, exist_ok=True)
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(current.isoformat() + "\n")
    except OSError:
        pass
    return current


def _list(value: Any, what: str) -> list:
    if not isinstance(value, list):
        raise ForgeError("payload_invalid", f"{what} is not an array")
    return value


def _object(value: Any, what: str) -> dict:
    if not isinstance(value, dict):
        raise ForgeError("payload_invalid", f"{what} is not an object")
    return value


def candidates(get: Get, repo: str, boundary: datetime) -> list[tuple[datetime, int, dict]]:
    """Every pull merged at or after the boundary with a head sha, ascending (merged_at, number)."""
    found: list[tuple[datetime, int, dict]] = []
    page = 1
    while True:
        items = _list(get(f"repos/{repo}/pulls?state=closed&sort=updated&direction=desc"
                          f"&per_page={PAGE}&page={page}"), "the pulls page")
        for item in items:
            pull = _object(item, "a pull")
            merged = parse_time(pull.get("merged_at"))
            head = _object(pull.get("head"), "a pull head").get("sha")
            if (merged is not None and merged >= boundary and isinstance(head, str)
                    and look_marker.HEAD_PATTERN.fullmatch(head) and isinstance(pull.get("number"), int)):
                found.append((merged, pull["number"], pull))
        last = parse_time(_object(items[-1], "a pull").get("updated_at")) if items else None
        if len(items) < PAGE or (last is not None and last < boundary):
            return sorted(found, key=lambda entry: (entry[0], entry[1]))
        page += 1


def hold_time(get: Get, repo: str, issue: int) -> datetime | None:
    """The `created_at` of the latest `labeled` event naming the held label, or None."""
    latest = None
    page = 1
    while True:
        events = _list(get(f"repos/{repo}/issues/{issue}/events?per_page={PAGE}&page={page}"),
                       "the events page")
        for event in events:
            event = _object(event, "an event")
            label = event.get("label")
            if (event.get("event") == "labeled" and isinstance(label, dict)
                    and label.get("name") == HELD_LABEL):
                created = parse_time(event.get("created_at"))
                if created is not None and (latest is None or created >= latest):
                    latest = created
        if len(events) < PAGE:
            return latest
        page += 1


def look_criteria(text: str) -> frozenset[int]:
    """The indexes of the acceptance criteria of an issue body whose line is a look marker."""
    recognized = look_marker.marker_lines(text)
    return frozenset(c.index for c in inbox.acceptance_criteria(text) if c.line + 1 in recognized)


def landing(get: Get, comments: Callable[[str, int], list], repo: str, boundary: datetime
            ) -> tuple[dict | None, tuple[int, int, datetime, datetime, frozenset[int]] | None]:
    """`(stop, None)` for a not-yet answer, `(None, (issue, pr, merged_at, held_at, looks))` for the
    landing, `(None, None)` when no marked issue landed under an approved look."""
    for merged, number, pull in candidates(get, repo, boundary):
        head = pull["head"]["sha"]
        body = pull.get("body")
        for issue in sorted({int(n) for n in CLOSES.findall(body if isinstance(body, str) else "")}):
            found = _object(get(f"repos/{repo}/issues/{issue}"), "an issue")
            text = found.get("body")
            text = text if isinstance(text, str) else ""
            if not look_marker.read_look(text).marked:
                continue
            answer = look_marker.look_answer(comments(repo, issue), issue, number, head)
            if answer is None or answer.fields.get("answer") != "approved":
                continue
            if found.get("state") == "closed":
                continue
            labels = [label.get("name") for label in _list(found.get("labels"), "the labels")
                      if isinstance(label, dict)]
            held = hold_time(get, repo, issue) if HELD_LABEL in labels else None
            if held is None:
                return {"issue": issue, "pr": number, "status": "not_held"}, None
            return None, (issue, number, merged, held, look_criteria(text))
    return None, None


def _projects(view: Mapping[str, Any]):
    for entry in view.get("entries") or []:
        if not isinstance(entry, dict):
            continue
        if entry.get("type") == "project":
            yield entry
        elif entry.get("type") == "quiet_group":
            yield from (p for p in entry.get("projects") or [] if isinstance(p, dict))


def _read_status(project: Mapping[str, Any], after: datetime) -> str | None:
    read = project.get("tracker_read")
    if not isinstance(read, dict):
        return "not_read"
    if read.get("ok") is not True:
        return "stale"
    began = parse_time(read.get("began_at"))
    return "not_read" if began is None or began < after else None


def judge_state(view: Mapping[str, Any], repo: str, issue: int, pr: int, after: datetime,
                looks: frozenset[int], slug_of: Callable[[str], str | None]) -> tuple[int, dict]:
    """The verdict of the console's view for the landing: `(exit code, output)`."""
    who = {"issue": issue, "pr": pr}
    statuses = [_read_status(project, after) for project in _projects(view)
                if (slug_of(project.get("root")) or "").lower() == repo.lower()]
    if not statuses:
        return NOT_YET, {**who, "status": "not_registered"}
    if None not in statuses:
        return NOT_YET, {**who, "status": statuses[0]}
    items = (view.get("inbox") or {}).get("open") or []
    keys = sorted(str(item.get("key")) for item in items if isinstance(item, dict)
                  and str(item.get("repo", "")).lower() == repo.lower()
                  and item.get("issue") == issue and item.get("kind") == REVIEW_KIND
                  and item.get("criterion") in looks)
    if keys:
        return 1, {**who, "keys": keys, "status": "not_met"}
    return 0, {**who, "status": "met"}


def _emit(code: int, out: dict) -> int:
    print(json.dumps(out, sort_keys=True))
    return code


def _parse(argv) -> argparse.Namespace:
    parser = _Parser(prog="look_check", add_help=False)
    parser.add_argument("--repo", required=True)
    parser.add_argument("--since", required=True)
    parser.add_argument("--url", default=DEFAULT_URL)
    args = parser.parse_args(argv)
    if not re.fullmatch(r"[\w.-]+/[\w.-]+", args.repo):
        raise Usage("--repo is not owner/name")
    if not look_marker.HEAD_PATTERN.fullmatch(args.since):
        raise Usage("--since is not 40 lowercase hex")
    parts = urlsplit(args.url)
    try:
        port = parts.port
    except ValueError:
        port = -1
    if parts.scheme != "http" or parts.hostname not in LOOPBACK or port == -1:
        raise Usage("--url must be http on 127.0.0.1 or localhost")
    return args


def main(argv=None, *, get=None, comments=None, state=None, activated_at=None,
         fixed_activation=None, slug_of=None) -> int:
    get = get or forge_api.api_get
    comments = comments or forge_markers.list_comments
    state = state or default_state
    activated_at = activated_at or default_activated_at
    fixed_activation = fixed_activation or default_fixed_activation
    slug_of = slug_of or owner_actions.checkout_slug
    try:
        args = _parse(sys.argv[1:] if argv is None else argv)
    except Usage as error:
        return _emit(2, {"status": "error", "detail": str(error)})
    activated = activated_at()
    if activated is None:
        return _emit(NOT_YET, {"status": "activation_unknown"})
    try:
        commit = _object(get(f"repos/{args.repo}/commits/{args.since}"), "the commit")
        merged_at = parse_time(_object(_object(commit.get("commit"), "commit").get("committer"),
                                       "committer").get("date"))
        if merged_at is None:
            raise ForgeError("payload_invalid", "the commit has no readable committer date")
        stop, found = landing(get, comments, args.repo,
                              max(merged_at, fixed_activation(args.since, activated)))
    except (ForgeError, KeyError, TypeError, AttributeError, ValueError) as error:
        return _emit(2, {"status": "error", "detail": str(error)[:300]})
    if stop is not None:
        return _emit(NOT_YET, stop)
    if found is None:
        return _emit(NOT_YET, {"status": "waiting"})
    issue, pr, merged, held, looks = found
    view = state(args.url)
    if view is None:
        return _emit(NOT_YET, {"issue": issue, "pr": pr, "status": "not_running"})
    return _emit(*judge_state(view, args.repo, issue, pr, max(held, merged), looks, slug_of))


if __name__ == "__main__":
    sys.exit(main())
