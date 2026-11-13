"""`capacity_check`: the verify check that the console shows a capacity reading for an account in use (#860).

`python -m agent_tools.console.capacity_check [--url URL] [--max-age SECONDS] [--every | --signin | --accounts | --exclusion]` reads the console's
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

A console that is down or predates this change is "not yet", never "not met", and only a reading
newer than `--max-age` meets the check. A bad argument is exit 2. The check only reads: it sends one
GET, follows no redirect and writes nothing.
"""

from __future__ import annotations

import argparse
import http.client
import json
import sys
from datetime import datetime, timezone
from urllib.parse import urlsplit

DEFAULT_URL = "http://127.0.0.1:27184/api/state"
DEFAULT_MAX_AGE = 600
LOOPBACK = ("127.0.0.1", "localhost")
TIMEOUT = 5.0
NOT_YET = 75


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
    args = build_parser().parse_args(argv)
    body = fetch(args.url)
    if body is None:
        print(json.dumps({"status": "not_running"}, sort_keys=True))
        return NOT_YET
    rows = readings(body)
    if rows is None:
        print(json.dumps({"status": "not_deployed"}, sort_keys=True))
        return NOT_YET
    if args.exclusion:
        return _exclusion(args.url, body)
    if args.accounts:
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
