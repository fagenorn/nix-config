"""`capacity_check`: the verify check that the console shows a capacity reading for an account in use (#860).

`python -m agent_tools.console.capacity_check [--url URL] [--max-age SECONDS] [--every | --signin | --accounts | --page-signin | --page-add | --code-signin | --pin | --page-remove | --exclusion | --account-names] [--after-seq N | --after-commit SHA] [--log PATH]` reads the console's
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

`--exclusion` (#1028, exclusive with `--every`, `--signin` and `--accounts`, `--max-age` ignored)
meets when the console's choice is a profile that is not excluded while another is. It sends two
GETs, the view and `/api/profile` on the same scheme, host and port, and decides in this order,
one stdout line of sorted-key JSON:

- the view does not answer 200: `{"status": "not_running"}`, exit 75;
- no `capacity` object: `{"status": "not_deployed"}`, exit 75;
- a row whose `excluded` is not a bool (the console predates exclusion):
  `{"status": "not_deployed"}`, exit 75;
- `/api/profile` does not answer 200, or its body is not a JSON object whose `profile` is a string
  or null: `{"status": "no_profile"}`, exit 75;
- otherwise, with `excluded` the names of the rows marked true in row order and `profile` the
  answer: no row excluded is `{"status": "pending", "profile": <p>, "excluded": []}`, exit 75;
  `profile` null is `{"status": "pending", "profile": null, "excluded": [<names>]}`, exit 75;
  `profile` among the excluded is `{"status": "not_met", "profile": <p>, "excluded": [<names>]}`,
  exit 1; else `{"status": "met", "profile": <p>, "excluded": [<names>]}`, exit 0.

`--page-signin` (#1026, exclusive with the other modes, `--max-age` ignored) meets when the owner has
signed a profile in from the page and its sign-in item is gone. Let S be the profiles whose
top-level `signin_runs[profile]` is an object with `state` `signed_in` (only `state` is read) and O
those of S with an open inbox item keyed `signin/<profile>`. A view whose `signin_runs` is not an
object is `{"status": "not_deployed"}`, exit 75; one whose `inbox.open` is not a list is
`{"status": "no_inbox"}`, exit 75; an empty S is `{"status": "pending"}`, exit 75 (no sign-in from
the page yet). Otherwise a profile of S not in O is `{"status": "met", "profiles": <S minus O,
sorted>}`, exit 0, and when every profile of S is in O `{"status": "not_met", "profiles": <S,
sorted>}`, exit 1.
`--after-seq N` reads only log rows whose `seq` is above N (a log carried over from another host
keeps its rows below N), and for `--page-signin` it also requires a `signin.ended` row with outcome
`signed_in` for the profile above N, read from `--log` or the console's own log (`{"status":
"no_log"}`, exit 75, when it cannot be read).

`--page-add` (#1027, #1037, exclusive with the other modes, `--max-age` ignored) meets when the
console's own event log shows an account added from the page whose sign-in the page then started.
It never asks the console and never looks at a profile, so no account has to stay on the host; the
`--url` is not used. The log is `--log PATH` or else `state_root()/console/events.sqlite3`
(`$HOME/.agents/state/console/events.sqlite3`), opened read-only (SQLite `mode=ro` with
`query_only`): it is never created, written, or given a journal. A profile P is in the set when the
log holds an `account.added` row whose payload has `by` `owner` and a non-empty string `profile` P,
and a later row (higher `seq`) of kind `signin.acted` whose payload has `by` `owner`, `action`
`start`, `outcome` `started` and `profile` P. The row kind `account.added` exists only from #1027,
so any such row is from a console that has that merge. A non-empty set is `{"status": "met",
"profiles": [<set, sorted>]}`, exit 0; an empty one `{"status": "pending"}`, exit 75. A log that is
missing, is not a database or lacks the `events` table is `{"status": "no_log"}`, exit 75. It never
exits 1: a row that is not there yet may still be recorded.
For `--page-add`, `--after-seq N` reads only log rows whose `seq` is above N (a log carried over
from another host keeps its rows below N), and the add and the start must both be above N.

`--code-signin` (#1323, exclusive with the other modes, `--max-age` and `--after-seq` not allowed) meets
when the console's own event log shows a sign-in finished by a code pasted into the page. It never
asks the console, so the `--url` is not used; the log is `--log PATH` or the console's own, opened
read-only as for `--page-add`. A profile P is in the set when, for one attempt A (the `seq` of the
start row), the log holds a `signin.acted` row at `seq` A whose payload has `by` `owner`, `action`
`start`, `outcome` `started` and `profile` P; a `signin.acted` row whose payload has `by` `owner`,
`action` `code`, `outcome` `sent` and `profile` P with `seq` above A; and a `signin.ended` row for P
with `attempt` A and `outcome` `signed_in` at a higher `seq` than that code.
A code counts only for the latest start of its profile. `--after-commit SHA` (40 lowercase hex)
keeps only rows whose `at` is strictly after the commit's committer time, read with `git show -s
--format=%cI SHA` in the current directory; all three rows must be later, the start included. A
non-empty set is `{"status": "met", "profiles": [<set, sorted>]}`, exit 0; an empty one `{"status":
"pending"}`, exit 75; an unreadable log `{"status": "no_log"}`, exit 75; a commit time Git cannot
give (a failure, a timeout or an unparsable time) `{"status": "no_commit"}`, exit 75. It never exits
1, and it only reads: no request, no write.

`--pin` (#1029, exclusive with the other modes, `--max-age` ignored) meets when a new session or
manager has started under a profile while the owner's page pin of that profile was in force. It
reads only the view's top-level `pin_launches` (the sorted profiles of such launches, which the
console folds from its event log), and decides in this order, one stdout line of sorted-key JSON:

- the view does not answer 200: `{"status": "not_running"}`, exit 75;
- no `capacity` object: `{"status": "not_deployed"}`, exit 75;
- `pin_launches` missing or not a list of strings (the console predates the pin):
  `{"status": "not_deployed"}`, exit 75;
- `pin_launches` empty: `{"status": "pending", "profiles": []}`, exit 75 (no launch under a pin
  is logged yet);
- otherwise `{"status": "met", "profiles": [<names, sorted and de-duplicated>]}`, exit 0.

No pin needs to be in force when it runs: it never reads the live `pin`, `/api/profile` or the
`chosen-profile` file, so the owner never has to leave the machine in a special state. It never
exits 1: the log cannot show whether a pin had room or whether a session used the `CLAUDE_ACCOUNT`
override, so no reading is "not met".

`--page-remove` (#1030, exclusive with the other modes, `--max-age` ignored) meets when the owner
removed an account from the page and it is gone. No state is needed on the host: the console's own
event log carries the owner action. The log is `--log PATH` or the console's own, opened exactly as
`--page-add` opens it (a missing log, a file that is not a database or one without the `events`
table is `{"status": "no_log"}`, exit 75). Rows of kind `account.added` and `account.removal`
are read in `seq` order; a payload counts only when it is an object whose `by` is `owner` and whose
`profile` is a non-empty string P. An add puts P in the added set and takes it out of the removed
set; a removal whose `outcome` is `removed` or `removed_signed_out_already` puts P in the removed
set only when P is in the added set. An empty removed set is `{"status": "pending"}`, exit 75 (the
view is not fetched). Then the view is read: no 200 is `{"status": "not_running"}`, exit 75, and no
`capacity` object `{"status": "not_deployed"}`, exit 75. A removed P is gone when no capacity row
names it and `profiles_dir() / P` does not exist (`os.path.lexists`), where `profiles_dir()` is
`$CLAUDE_ACCOUNTS_DIR` or else `~/.claude-accounts`, then `/profiles`. Some gone is `{"status":
"met", "profiles": [<gone, sorted>]}`, exit 0; otherwise `{"status": "not_met", "profiles":
[<removed, sorted>]}`, exit 1. It writes nothing, sends one GET at most and touches the accounts
directory only to look for a name. `--after-seq N` reads only log rows whose `seq` is above N (a
log carried over from another host keeps its rows below N), so the add and the removal must both be
above N.

`--account-names` (#1036, exclusive with the other modes, `--max-age` ignored) meets when every
signed-in profile carries the name its client reports and the Sign in again action. It decides in
this order, after the `not_running` and `not_deployed` answers above, one stdout line of sorted-key
JSON. The rows are the `capacity.profiles` objects with a string `profile`; a row without an
`account` member means the console predates the name: `{"status": "not_deployed"}`, exit 75. S is
the rows whose `signin` is an object with `state` `signed_in`; an empty S is `{"status": "pending",
"profiles": []}`, exit 75. The rows of S whose `account` is not a non-empty string or whose
`signin.ever_signed_in` is not `true` are missing: any is `{"status": "pending", "profiles":
[<missing names, row order>]}`, exit 75, because a signed-in profile gets its name at its next
reading, within 10 minutes. Otherwise `{"status": "met", "profiles": <len S>, "accounts": <number
of distinct accounts in S>}`, exit 0. It never exits 1 and prints no account string, because its
stdout is posted on the tracker.

A console that is down or predates this change is "not yet", never "not met", and only a reading
newer than `--max-age` meets the check. A bad argument is exit 2. The check only reads: it sends one
GET (none with `--page-add`, none with `--page-remove` before a removal is logged), follows no
redirect and writes nothing.
"""

from __future__ import annotations

import argparse
import http.client
import json
import os
import re
import sqlite3
import subprocess
import sys
from datetime import datetime, timezone
from collections.abc import Callable
from pathlib import Path
from urllib.parse import urlsplit

from agent_tools.project_contract import agent_platform

DEFAULT_URL = "http://127.0.0.1:27184/api/state"
DEFAULT_MAX_AGE = 600
LOOPBACK = ("127.0.0.1", "localhost")
TIMEOUT = 5.0
NOT_YET = 75
GIT_TIMEOUT = 10
# The entries the launcher links into a profile: the `SHARED=(...)` array of claude-account
# (kept for the accounts sandbox's snapshot, which lists a profile's shared entries).
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


def profile_url(url: str) -> str:
    """`url` with the path `/api/profile` and no query: the same scheme, host and port."""
    parts = urlsplit(url)
    return parts._replace(path="/api/profile", query="", fragment="").geturl()


def exclusion_rows(body: bytes) -> list[tuple[str, object]] | None:
    """The `(profile, excluded)` rows of a console view, None when it has no capacity object.

    `excluded` is the row's raw member, None when absent."""
    rows = readings(body)
    if rows is None:
        return None
    document = json.loads(body)
    return [(row["profile"], row.get("excluded"))
            for row in document["capacity"]["profiles"]
            if isinstance(row, dict) and isinstance(row.get("profile"), str)]


def chosen_profile(body: bytes | None) -> tuple[bool, object]:
    """`(True, profile)` when `body` is a JSON object whose `profile` is a string or null."""
    try:
        document = json.loads(body) if body is not None else None
    except ValueError:
        return False, None
    if isinstance(document, dict) and "profile" in document:
        chosen = document["profile"]
        if chosen is None or isinstance(chosen, str):
            return True, chosen
    return False, None


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


def exclusion_verdict(rows: list[tuple[str, object]], chosen: object) -> tuple[int, dict]:
    """Met when a profile is excluded and the choice names another one."""
    excluded = [name for name, flag in rows if flag is True]
    result = {"profile": chosen, "excluded": excluded}
    if not excluded or chosen is None:
        return NOT_YET, {"status": "pending", **result}
    if chosen in excluded:
        return 1, {"status": "not_met", **result}
    return 0, {"status": "met", **result}


def page_signin_verdict(body: bytes, signed_in_after: set[str] | None = None) -> tuple[int, dict]:
    """Met when a profile signed in from the page has no open sign-in item, else not yet or not met.

    A set `signed_in_after` limits the signed-in profiles to those it holds."""
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
    if signed_in_after is not None:
        signed_in = [name for name in signed_in if name in signed_in_after]
    if not signed_in:
        return NOT_YET, {"status": "pending"}
    cleared = [name for name in signed_in if f"signin/{name}" not in asks]
    if cleared:
        return 0, {"status": "met", "profiles": cleared}
    return 1, {"status": "not_met", "profiles": signed_in}


def account_names_verdict(body: bytes) -> tuple[int, dict]:
    """Met when every signed-in row names its account and has `ever_signed_in`; prints no name."""
    try:
        document = json.loads(body)
    except ValueError:
        document = None
    capacity = document.get("capacity") if isinstance(document, dict) else None
    listed = capacity.get("profiles") if isinstance(capacity, dict) else None
    rows = [row for row in listed if isinstance(row, dict) and isinstance(row.get("profile"), str)
            ] if isinstance(listed, list) else []
    if any("account" not in row for row in rows):
        return NOT_YET, {"status": "not_deployed"}
    signed_in = [row for row in rows
                 if isinstance(row.get("signin"), dict) and row["signin"].get("state") == "signed_in"]
    missing = [row["profile"] for row in signed_in
               if not (isinstance(row["account"], str) and row["account"])
               or row["signin"].get("ever_signed_in") is not True]
    if not signed_in or missing:
        return NOT_YET, {"status": "pending", "profiles": missing}
    return 0, {"status": "met", "profiles": len(signed_in),
               "accounts": len({row["account"] for row in signed_in})}


def default_log() -> Path:
    """The console's event log: `state_root()/console/events.sqlite3`."""
    return agent_platform.state_root() / "console" / "events.sqlite3"


def _owner(payload: object) -> bool:
    return isinstance(payload, dict) and payload.get("by") == "owner"


def profiles_dir() -> Path:
    """The launcher's profiles directory, under `$CLAUDE_ACCOUNTS_DIR` or `~/.claude-accounts`."""
    root = os.environ.get("CLAUDE_ACCOUNTS_DIR") or Path.home() / ".claude-accounts"
    return Path(root) / "profiles"


def _after(after_seq: int | None) -> tuple[str, tuple[int, ...]]:
    """The SQL tail and its parameters that keep only rows above `after_seq`."""
    if after_seq is None:
        return "", ()
    return " AND seq > ?", (after_seq,)


def signed_in_after(log: Path, after_seq: int) -> set[str] | None:
    """The profiles with a `signin.ended` `signed_in` row above `after_seq`; None if unreadable."""
    try:
        connection = sqlite3.connect(f"{log.resolve().as_uri()}?mode=ro", uri=True)
    except (sqlite3.Error, OSError):
        return None
    try:
        connection.execute("PRAGMA query_only = ON")
        rows = connection.execute(
            "SELECT payload FROM events WHERE kind = 'signin.ended' AND seq > ? ORDER BY seq",
            (after_seq,)).fetchall()
    except sqlite3.Error:
        return None
    finally:
        connection.close()
    profiles: set[str] = set()
    for (text,) in rows:
        try:
            payload = json.loads(text)
        except ValueError:
            continue
        profile = payload.get("profile") if isinstance(payload, dict) else None
        if (isinstance(payload, dict) and payload.get("outcome") == "signed_in"
                and isinstance(profile, str) and profile):
            profiles.add(profile)
    return profiles


def page_add_verdict(log: Path, after_seq: int | None = None) -> tuple[int, dict]:
    """Met when the log holds an owner `account.added` row and a later page sign-in start of it."""
    tail, bound = _after(after_seq)
    try:
        connection = sqlite3.connect(f"{log.resolve().as_uri()}?mode=ro", uri=True)
    except (sqlite3.Error, OSError):
        return NOT_YET, {"status": "no_log"}
    try:
        connection.execute("PRAGMA query_only = ON")
        rows = connection.execute(
            "SELECT kind, payload FROM events WHERE kind IN ('account.added', 'signin.acted')"
            f"{tail} ORDER BY seq", bound).fetchall()
    except sqlite3.Error:
        return NOT_YET, {"status": "no_log"}
    finally:
        connection.close()
    added: set[str] = set()
    started: set[str] = set()
    for kind, text in rows:
        try:
            payload = json.loads(text)
        except ValueError:
            continue
        profile = payload.get("profile") if isinstance(payload, dict) else None
        if not _owner(payload) or not isinstance(profile, str) or not profile:
            continue
        if kind == "account.added":
            added.add(profile)
        elif (payload.get("action") == "start" and payload.get("outcome") == "started"
              and profile in added):
            started.add(profile)
    if started:
        return 0, {"status": "met", "profiles": sorted(started)}
    return NOT_YET, {"status": "pending"}


def commit_time(sha: str) -> datetime | None:
    """The committer time of `sha` in the current directory; None when Git cannot give it."""
    try:
        done = subprocess.run(["git", "show", "-s", "--format=%cI", sha], capture_output=True,
                              text=True, timeout=GIT_TIMEOUT)
        if done.returncode != 0:
            return None
        return datetime.fromisoformat(done.stdout.strip())
    except (OSError, subprocess.TimeoutExpired, ValueError):
        return None


def _later(text: object, after: datetime | None) -> bool:
    """Whether the row time `text` parses and is strictly after `after` (always, when None)."""
    if after is None:
        return True
    try:
        at = datetime.fromisoformat(text)
    except (TypeError, ValueError):
        return False
    if at.tzinfo is None or after.tzinfo is None:
        return False
    return at > after


def code_signin_verdict(log: Path, after: datetime | None = None) -> tuple[int, dict]:
    """Met when the log shows an owner start, a pasted code inside it and its signed-in end."""
    try:
        connection = sqlite3.connect(f"{log.resolve().as_uri()}?mode=ro", uri=True)
    except (sqlite3.Error, OSError):
        return NOT_YET, {"status": "no_log"}
    try:
        connection.execute("PRAGMA query_only = ON")
        rows = connection.execute(
            "SELECT seq, at, kind, payload FROM events "
            "WHERE kind IN ('signin.acted', 'signin.ended') ORDER BY seq").fetchall()
    except sqlite3.Error:
        return NOT_YET, {"status": "no_log"}
    finally:
        connection.close()
    starts: dict[int, str] = {}
    latest: dict[str, int] = {}
    coded: dict[int, int] = {}
    met: set[str] = set()
    for seq, at, kind, text in rows:
        if not _later(at, after):
            continue
        try:
            payload = json.loads(text)
        except ValueError:
            continue
        profile = payload.get("profile") if isinstance(payload, dict) else None
        if not isinstance(payload, dict) or not isinstance(profile, str) or not profile:
            continue
        if kind == "signin.acted" and _owner(payload):
            if payload.get("action") == "start" and payload.get("outcome") == "started":
                starts[seq] = profile
                latest[profile] = seq
            elif (payload.get("action") == "code" and payload.get("outcome") == "sent"
                  and profile in latest):
                coded.setdefault(latest[profile], seq)
        elif kind == "signin.ended" and payload.get("outcome") == "signed_in":
            attempt = payload.get("attempt")
            if (isinstance(attempt, int) and not isinstance(attempt, bool)
                    and starts.get(attempt) == profile and attempt in coded):
                met.add(profile)
    if met:
        return 0, {"status": "met", "profiles": sorted(met)}
    return NOT_YET, {"status": "pending"}


REMOVED_OUTCOMES = ("removed", "removed_signed_out_already")


def page_remove_verdict(log: Path, body_of: Callable[[], bytes | None],
                        profiles: Path, after_seq: int | None = None) -> tuple[int, dict]:
    """Met when the log shows an owner add then removal of a profile the view and disk lack."""
    tail, bound = _after(after_seq)
    try:
        connection = sqlite3.connect(f"{log.resolve().as_uri()}?mode=ro", uri=True)
    except (sqlite3.Error, OSError):
        return NOT_YET, {"status": "no_log"}
    try:
        connection.execute("PRAGMA query_only = ON")
        rows = connection.execute(
            "SELECT kind, payload FROM events WHERE kind IN ('account.added', 'account.removal')"
            f"{tail} ORDER BY seq", bound).fetchall()
    except sqlite3.Error:
        return NOT_YET, {"status": "no_log"}
    finally:
        connection.close()
    added: set[str] = set()
    removed: set[str] = set()
    for kind, text in rows:
        try:
            payload = json.loads(text)
        except ValueError:
            continue
        profile = payload.get("profile") if isinstance(payload, dict) else None
        if not _owner(payload) or not isinstance(profile, str) or not profile:
            continue
        if kind == "account.added":
            added.add(profile)
            removed.discard(profile)
        elif payload.get("outcome") in REMOVED_OUTCOMES and profile in added:
            removed.add(profile)
    if not removed:
        return NOT_YET, {"status": "pending"}
    body = body_of()
    if body is None:
        return NOT_YET, {"status": "not_running"}
    listed = readings(body)
    if listed is None:
        return NOT_YET, {"status": "not_deployed"}
    names = {name for name, _, _ in listed}
    gone = sorted(name for name in removed
                  if name not in names and not os.path.lexists(profiles / name))
    if gone:
        return 0, {"status": "met", "profiles": gone}
    return 1, {"status": "not_met", "profiles": sorted(removed)}


def pin_verdict(body: bytes) -> tuple[int, dict]:
    """Met when the log shows a launch under the owner's pin; never read from the live pin."""
    try:
        document = json.loads(body)
    except ValueError:
        document = None
    launches = document.get("pin_launches") if isinstance(document, dict) else None
    if not isinstance(launches, list) or not all(isinstance(name, str) for name in launches):
        return NOT_YET, {"status": "not_deployed"}
    if not launches:
        return NOT_YET, {"status": "pending", "profiles": []}
    return 0, {"status": "met", "profiles": sorted(set(launches))}


def _sha(text: str) -> str:
    if not re.fullmatch(r"[0-9a-f]{40}", text):
        raise argparse.ArgumentTypeError("must be 40 lowercase hex digits")
    return text


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
    mode.add_argument("--exclusion", action="store_true",
                      help="require the console's choice to be a profile that is not excluded "
                           "while another is")
    mode.add_argument("--page-signin", action="store_true",
                      help="require a profile the owner signed in from the page whose sign-in "
                           "item is gone")
    mode.add_argument("--page-add", action="store_true",
                      help="require the console's log to show an account added from the page "
                           "and that profile's sign-in started from the page")
    mode.add_argument("--code-signin", action="store_true",
                      help="require the console's log to show a sign-in finished by a code "
                           "pasted into the page")
    mode.add_argument("--pin", action="store_true",
                      help="require a new session or manager started under a profile while the "
                           "owner's pin of it was in force, read from the console's log")
    mode.add_argument("--page-remove", action="store_true",
                      help="require an account the owner added and removed from the page to be "
                           "gone from the console's view and the profiles directory, read from "
                           "the console's log")
    mode.add_argument("--account-names", action="store_true",
                      help="require every signed-in profile to carry the account name its client "
                           "reports and the Sign in again action; prints no name")
    parser.add_argument("--log", type=Path, default=None,
                        help="the console event log for --page-add and --page-remove, and for "
                             "--page-signin with --after-seq (default: the console's own)")
    parser.add_argument("--after-seq", type=_positive, default=None,
                        help="read only log rows whose seq is above this, for --page-signin, "
                             "--page-add and --page-remove")
    parser.add_argument("--after-commit", type=_sha, default=None,
                        help="read only log rows stamped after this commit's time, for "
                             "--code-signin")
    return parser


def _exclusion(url: str, body: bytes) -> int:
    rows = exclusion_rows(body)
    if any(not isinstance(flag, bool) for _, flag in rows):
        code, result = NOT_YET, {"status": "not_deployed"}
    else:
        known, chosen = chosen_profile(fetch(profile_url(url)))
        if known:
            code, result = exclusion_verdict(rows, chosen)
        else:
            code, result = NOT_YET, {"status": "no_profile"}
    print(json.dumps(result, sort_keys=True))
    return code


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.after_seq is not None and not (args.page_signin or args.page_add or args.page_remove):
        parser.error("--after-seq applies to --page-signin, --page-add and --page-remove only")
    if args.after_commit is not None and not args.code_signin:
        parser.error("--after-commit applies to --code-signin only")
    if args.code_signin:
        after = None
        if args.after_commit is not None:
            after = commit_time(args.after_commit)
            if after is None:
                print(json.dumps({"status": "no_commit"}, sort_keys=True))
                return NOT_YET
        code, result = code_signin_verdict(args.log or default_log(), after)
        print(json.dumps(result, sort_keys=True))
        return code
    if args.page_add:
        code, result = page_add_verdict(args.log or default_log(), args.after_seq)
        print(json.dumps(result, sort_keys=True))
        return code
    if args.page_remove:
        code, result = page_remove_verdict(args.log or default_log(), lambda: fetch(args.url),
                                           profiles_dir(), args.after_seq)
        print(json.dumps(result, sort_keys=True))
        return code
    body = fetch(args.url)
    if body is None:
        print(json.dumps({"status": "not_running"}, sort_keys=True))
        return NOT_YET
    rows = readings(body)
    if rows is None:
        print(json.dumps({"status": "not_deployed"}, sort_keys=True))
        return NOT_YET
    if args.page_signin and args.after_seq is not None:
        ended = signed_in_after(args.log or default_log(), args.after_seq)
        if ended is None:
            print(json.dumps({"status": "no_log"}, sort_keys=True))
            return NOT_YET
        code, result = page_signin_verdict(body, ended)
        print(json.dumps(result, sort_keys=True))
        return code
    if args.exclusion:
        return _exclusion(args.url, body)
    if args.account_names:
        code, result = account_names_verdict(body)
    elif args.pin:
        code, result = pin_verdict(body)
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
