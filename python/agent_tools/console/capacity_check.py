"""`capacity_check`: the verify check that the console shows a capacity reading for an account in use (#860).

`python -m agent_tools.console.capacity_check [--url URL] [--max-age SECONDS] [--every | --signin | --accounts | --page-signin | --page-add]` reads the console's
`/api/state` view (default `http://127.0.0.1:27184/api/state`; the URL must be `http` on a loopback
host, `127.0.0.1` or `localhost`, else exit 2) and looks at `capacity.profiles[].read_at`.
`--max-age` is a positive integer number of seconds (default 600).

Output is one stdout line of JSON with sorted keys:

- the URL does not answer (connection refused, timeout of 5 s, any status but 200):
  `{"status": "not_running"}`, exit 75;
- the body is not JSON or has no `capacity` object: `{"status": "not_deployed"}`, exit 75;
- some profile's `read_at` parses as an ISO 8601 time and is at most `--max-age` seconds before now:
  `{"status": "met", "profile": <name>, "age_seconds": <int>}` for the freshest such profile,
  exit 0;
- otherwise `{"status": "not_met", "profiles": [<names>]}`, exit 1.

With `--every` (#1009) the check meets only when every listed profile has a fresh reading: at least
one row, and every row's `read_at` parses and is at most `--max-age` seconds before now. Then
`{"status": "met", "profiles": <row count>, "oldest_age_seconds": <largest age>}`, exit 0. Otherwise
`{"status": "pending", "profiles": [<names whose reading is missing, unreadable or older than
--max-age, in row order>]}`, exit 75; an empty view is pending with `[]`. `--every` never exits 1,
because the check cannot see when the host was activated, so a missing reading may still arrive.

`--every` leaves out each row whose `signin` member (#1010) is an object with `state` `signed_out`:
a profile that holds no sign-in has no reading to wait for. Over the remaining rows the rule is
the one above, and it is met when at least one remains and none is stale, as
`{"status": "met", "profiles": <remaining count>, "oldest_age_seconds": <largest age>,
"signed_out": [<skipped names, row order>]}`; all rows signed out is pending with `[]`.

`--signin` (#1010, exclusive with `--every`, `--max-age` ignored) meets when every listed profile
knows its sign-in: at least one row and every row's `signin.state` is `signed_in` or `signed_out`.
Then `{"status": "met", "profiles": <row count>, "signed_out": [<names>]}`, exit 0. Otherwise
`{"status": "pending", "profiles": [<names whose state is anything else, in row order>]}`, exit 75
(an empty view is pending with `[]`). A row whose `signin` is not an object with a string `state`
means the console predates sign-in: `{"status": "not_deployed"}`, exit 75. It never exits 1.

`--accounts` (#1016, exclusive with `--every` and `--signin`, `--max-age` ignored) meets when the
view lists at least one profile, none named `default`, and no open inbox item is keyed
`signin/default`: `{"status": "met", "profiles": [<names>]}`, exit 0. A view whose `inbox.open` is
not a list (no `inbox` object, or no `open` list) is `{"status": "no_inbox"}`, exit 75: the item's
absence is never inferred from missing data. Otherwise a `default` row or that item is
`{"status": "not_met", "default_row": <bool>, "default_signin": <bool>}`, exit 1; no row is
`{"status": "pending", "profiles": []}`, exit 75.

`--page-signin` (#1026, exclusive with the other modes, `--max-age` ignored) meets when the owner has
signed a profile in from the page and its sign-in item is gone. Let S be the profiles whose
top-level `signin_runs[profile]` is an object with `state` `signed_in` (only `state` is read) and O
those of S with an open inbox item keyed `signin/<profile>`. A view whose `signin_runs` is not an
object is `{"status": "not_deployed"}`, exit 75; one whose `inbox.open` is not a list is
`{"status": "no_inbox"}`, exit 75; an empty S is `{"status": "pending"}`, exit 75 (no sign-in from
the page yet). Otherwise a profile of S not in O is `{"status": "met", "profiles": <S minus O,
sorted>}`, exit 0, and when every profile of S is in O `{"status": "not_met", "profiles": <S,
sorted>}`, exit 1.

`--page-add` (#1027, exclusive with the other modes, `--max-age` ignored) meets when an account the
owner added from the page has the profile the launcher builds and its sign-in is done. Let A be the
view's top-level `accounts_added`, home `Path.home()` and accounts `$CLAUDE_ACCOUNTS_DIR` or else
`home/.claude-accounts`. The expected entries are the members `e` of `SHARED` (the launcher's
`SHARED` array) with `os.path.lexists(home/.claude/e)`, the launcher's own test before it links. A
view whose `accounts_added` is not a list of strings, or whose `capacity.profiles` is unreadable, is
`{"status": "not_deployed"}`, exit 75. For each name in sorted A whose `accounts/profiles/<name>` is
a directory (a missing one is skipped as removed) the profile is malformed unless its mode is
`0o700`, every expected entry `e` is a symlink there (by `os.lstat`, never followed; a missing
entry, or a file or directory in its place, is malformed) whose `os.readlink` is
`str(home/.claude/e)`, and every other symlink in it reads `str(home/.claude/<its name>)`. Any
malformed profile is `{"status": "not_met", "profiles": [<malformed, sorted>]}`, exit 1. Otherwise
the well-formed names whose `capacity.profiles` row has `signin.state` `signed_in` give `{"status":
"met", "profiles": [<those, sorted>]}`, exit 0, and when there are none `{"status": "pending",
"profiles": [<well-formed present names, sorted>]}`, exit 75.

A console that is down or predates this change is "not yet", never "not met", and only a reading
newer than `--max-age` meets the check. A bad argument is exit 2. The check only reads: it sends one
GET, follows no redirect and writes nothing.
"""

from __future__ import annotations

import argparse
import http.client
import json
import os
import stat
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

DEFAULT_URL = "http://127.0.0.1:27184/api/state"
DEFAULT_MAX_AGE = 600
LOOPBACK = ("127.0.0.1", "localhost")
TIMEOUT = 5.0
NOT_YET = 75
# The entries the launcher links into a profile: the `SHARED=(...)` array of claude-account.
SHARED = ("settings.json", "CLAUDE.md", "keybindings.json", "skills", "agents", "commands",
          "plugins", "projects", "file-history", "history.jsonl", "output-styles", "rules")


def _loopback_url(text: str) -> str:
    try:
        parts = urlsplit(text)
        parts.port  # noqa: B018  raises ValueError on a bad port
    except ValueError:
        raise argparse.ArgumentTypeError(f"not a URL: {text}") from None
    if parts.scheme != "http" or parts.hostname not in LOOPBACK:
        raise argparse.ArgumentTypeError("the URL must be http on 127.0.0.1 or localhost")
    return text


def _positive(text: str) -> int:
    try:
        value = int(text)
    except ValueError:
        raise argparse.ArgumentTypeError(f"not an integer: {text}") from None
    if value < 1:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return value


def fetch(url: str) -> bytes | None:
    """The body of a 200 answer to a GET of `url`, else None."""
    parts = urlsplit(url)
    path = (parts.path or "/") + (f"?{parts.query}" if parts.query else "")
    connection = http.client.HTTPConnection(parts.hostname, parts.port, timeout=TIMEOUT)
    try:
        connection.request("GET", path)
        response = connection.getresponse()
        body = response.read()
        return body if response.status == 200 else None
    except (OSError, http.client.HTTPException):
        return None
    finally:
        connection.close()


def readings(body: bytes) -> list[tuple[str, object, object]] | None:
    """The `(profile, read_at, signin)` rows of a console view, None when it has no capacity object.

    `signin` is the row's raw `signin` member, None when absent."""
    try:
        document = json.loads(body)
    except ValueError:
        return None
    capacity = document.get("capacity") if isinstance(document, dict) else None
    if not isinstance(capacity, dict):
        return None
    profiles = capacity.get("profiles")
    rows = []
    for row in profiles if isinstance(profiles, list) else []:
        if isinstance(row, dict) and isinstance(row.get("profile"), str):
            rows.append((row["profile"], row.get("read_at"), row.get("signin")))
    return rows


def signin_asks(body: bytes) -> list[str] | None:
    """The key of each open `signin/...` inbox item, in order; None when the inbox is unreadable.

    None means `inbox.open` could not be read (not JSON, no `inbox` object, no `open` list), never
    that it is empty."""
    try:
        document = json.loads(body)
    except ValueError:
        return None
    inbox = document.get("inbox") if isinstance(document, dict) else None
    items = inbox.get("open") if isinstance(inbox, dict) else None
    if not isinstance(items, list):
        return None
    return [item["key"] for item in items
            if isinstance(item, dict) and isinstance(item.get("key"), str)
            and item["key"].startswith("signin/")]


def age_seconds(read_at: object, now: datetime) -> int | None:
    """Whole seconds from `read_at` to `now` (0 for a time ahead of it), None when unreadable."""
    if not isinstance(read_at, str):
        return None
    try:
        moment = datetime.fromisoformat(read_at)
    except ValueError:
        return None
    if moment.tzinfo is None:
        return None
    return max(0, int((now - moment).total_seconds()))


def verdict(rows: list[tuple[str, object, object]], max_age: int,
            now: datetime) -> tuple[int, dict]:
    ages = [(age, name) for name, read_at, _ in rows
            if (age := age_seconds(read_at, now)) is not None]
    if ages and min(ages)[0] <= max_age:
        age, name = min(ages)
        return 0, {"status": "met", "profile": name, "age_seconds": age}
    return 1, {"status": "not_met", "profiles": [name for name, _, _ in rows]}


def _state(signin: object) -> object:
    return signin.get("state") if isinstance(signin, dict) else None


def every_verdict(rows: list[tuple[str, object, object]], max_age: int,
                  now: datetime) -> tuple[int, dict]:
    """Met when a signed-in row remains and every one is fresh, else pending on the stale ones."""
    signed_out = [name for name, _, signin in rows if _state(signin) == "signed_out"]
    kept = [(name, read_at) for name, read_at, signin in rows if _state(signin) != "signed_out"]
    ages = [age_seconds(read_at, now) for _, read_at in kept]
    stale = [name for (name, _), age in zip(kept, ages) if age is None or age > max_age]
    if kept and not stale:
        return 0, {"status": "met", "profiles": len(kept), "oldest_age_seconds": max(ages),
                   "signed_out": signed_out}
    return NOT_YET, {"status": "pending", "profiles": stale}


def signin_verdict(rows: list[tuple[str, object, object]]) -> tuple[int, dict]:
    """Met when there is a row and every row's sign-in is known, else pending on the others."""
    if any(not isinstance(_state(signin), str) for _, _, signin in rows):
        return NOT_YET, {"status": "not_deployed"}
    known = ("signed_in", "signed_out")
    pending = [name for name, _, signin in rows if _state(signin) not in known]
    if rows and not pending:
        return 0, {"status": "met", "profiles": len(rows),
                   "signed_out": [name for name, _, signin in rows
                                  if _state(signin) == "signed_out"]}
    return NOT_YET, {"status": "pending", "profiles": pending}


def accounts_verdict(rows: list[tuple[str, object, object]],
                     asks: list[str] | None) -> tuple[int, dict]:
    """Met when there is a row, none is `default` and no sign-in item is for `default`."""
    if asks is None:
        return NOT_YET, {"status": "no_inbox"}
    if not rows:
        return NOT_YET, {"status": "pending", "profiles": []}
    default_row = any(name == "default" for name, _, _ in rows)
    default_signin = "signin/default" in asks
    if default_row or default_signin:
        return 1, {"status": "not_met", "default_row": default_row,
                   "default_signin": default_signin}
    return 0, {"status": "met", "profiles": [name for name, _, _ in rows]}


def page_signin_verdict(body: bytes) -> tuple[int, dict]:
    """Met when a profile signed in from the page has no open sign-in item, else not yet or not met."""
    try:
        document = json.loads(body)
    except ValueError:
        document = None
    runs = document.get("signin_runs") if isinstance(document, dict) else None
    if not isinstance(runs, dict):
        return NOT_YET, {"status": "not_deployed"}
    asks = signin_asks(body)
    if asks is None:
        return NOT_YET, {"status": "no_inbox"}
    signed_in = sorted(name for name, run in runs.items()
                       if isinstance(run, dict) and run.get("state") == "signed_in")
    if not signed_in:
        return NOT_YET, {"status": "pending"}
    cleared = [name for name in signed_in if f"signin/{name}" not in asks]
    if cleared:
        return 0, {"status": "met", "profiles": cleared}
    return 1, {"status": "not_met", "profiles": signed_in}


def _links_to(path: str, target: Path) -> bool:
    try:
        return stat.S_ISLNK(os.lstat(path).st_mode) and os.readlink(path) == str(target)
    except OSError:
        return False


def _well_formed(profile: Path, home: Path, expected: list[str]) -> bool:
    """The profile the launcher builds: mode 0700, a link to `~/.claude/<e>` for each expected `e`."""
    base = home / ".claude"
    try:
        if stat.S_IMODE(os.lstat(profile).st_mode) != 0o700:
            return False
        if not all(_links_to(str(profile / entry), base / entry) for entry in expected):
            return False
        with os.scandir(profile) as entries:
            return all(_links_to(entry.path, base / entry.name)
                       for entry in entries if entry.is_symlink())
    except OSError:
        return False


def page_add_verdict(body: bytes, home: Path, accounts: Path) -> tuple[int, dict]:
    """Met when a page-added profile is the launcher's profile and signed in, else not yet or not met."""
    try:
        document = json.loads(body)
    except ValueError:
        document = None
    added = document.get("accounts_added") if isinstance(document, dict) else None
    rows = readings(body)
    if (not isinstance(added, list) or not all(isinstance(name, str) for name in added)
            or rows is None):
        return NOT_YET, {"status": "not_deployed"}
    expected = [entry for entry in SHARED if os.path.lexists(home / ".claude" / entry)]
    present = [name for name in sorted(set(added)) if (accounts / "profiles" / name).is_dir()]
    good = [name for name in present
            if _well_formed(accounts / "profiles" / name, home, expected)]
    malformed = [name for name in present if name not in good]
    if malformed:
        return 1, {"status": "not_met", "profiles": malformed}
    signed_in = {name for name, _, signin in rows if _state(signin) == "signed_in"}
    done = [name for name in good if name in signed_in]
    if done:
        return 0, {"status": "met", "profiles": done}
    return NOT_YET, {"status": "pending", "profiles": good}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="capacity_check", description=__doc__.splitlines()[0])
    parser.add_argument("--url", type=_loopback_url, default=DEFAULT_URL,
                        help="the console state view to read (default: %(default)s)")
    parser.add_argument("--max-age", type=_positive, default=DEFAULT_MAX_AGE,
                        help="newest reading allowed, in seconds (default: %(default)s)")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--every", action="store_true",
                      help="require a fresh reading for every signed-in profile; a missing one "
                           "is not yet")
    mode.add_argument("--signin", action="store_true",
                      help="require every listed profile to know its sign-in (signed in or "
                           "signed out)")
    mode.add_argument("--accounts", action="store_true",
                      help="require the listed profiles to be named accounts only: no default "
                           "row and no sign-in item for default")
    mode.add_argument("--page-signin", action="store_true",
                      help="require a profile the owner signed in from the page whose sign-in "
                           "item is gone")
    mode.add_argument("--page-add", action="store_true",
                      help="require an account the owner added from the page to be the "
                           "launcher's profile and signed in")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    body = fetch(args.url)
    if body is None:
        print(json.dumps({"status": "not_running"}, sort_keys=True))
        return NOT_YET
    rows = readings(body)
    if rows is None:
        print(json.dumps({"status": "not_deployed"}, sort_keys=True))
        return NOT_YET
    if args.page_add:
        home = Path.home()
        accounts = Path(os.environ.get("CLAUDE_ACCOUNTS_DIR") or home / ".claude-accounts")
        code, result = page_add_verdict(body, home, accounts)
    elif args.page_signin:
        code, result = page_signin_verdict(body)
    elif args.accounts:
        code, result = accounts_verdict(rows, signin_asks(body))
    elif args.signin:
        code, result = signin_verdict(rows)
    else:
        decide = every_verdict if args.every else verdict
        code, result = decide(rows, args.max_age, datetime.now(timezone.utc))
    print(json.dumps(result, sort_keys=True))
    return code


if __name__ == "__main__":
    sys.exit(main())
