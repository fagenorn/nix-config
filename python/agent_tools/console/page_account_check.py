"""`page_account_check`: the verify check that a throwaway profile is added and removed through the console's page (#894).

`python -m agent_tools.console.page_account_check (--page-add | --page-remove) --after-seq N [--url URL]
[--token-file PATH] [--name NAME]` produces the log rows that `capacity_check --page-add` and
`--page-remove` read, then delegates to that reading. `--url` is the console's base URL (default
`http://127.0.0.1:27184`; `http` on `127.0.0.1` or `localhost`, else exit 2); `--after-seq` is required, a
positive log watermark, passed on to the reading; `--token-file` defaults to
`<state_root()>/console/page-token`; `--name` defaults to `zzcheck-mac` and must match the account name
rule (else exit 2).

This check writes to the owner's console: it adds a profile and removes it, so it is an `effects: live`
check, run only where the verify runner has an approval for it, never against the live console unasked.

Met first. The reading is made before anything else; when it is already met the check prints its line and
exits 0, posting nothing and not reading the token file, so a second run after the first adds no profile.

Round trip. Otherwise the token file is read (unreadable: `{"status": "no_token"}`, exit 75, nothing
posted) and the check posts, with the page's write headers, `/api/account-add` `{"name": NAME}`, then
cleans up, then reads again and exits with that reading's exit and prints its line. The clean-up posts
`/api/signin-cancel` `{"profile": NAME}` (any answer accepted) then `/api/account-remove`
`{"profile": NAME, "typed": NAME}`, which is retried after 5 seconds while the console answers that the
profile is still being read or that its cancelled sign-in is still running (the run leaves the console's
running set a moment after the cancel answers), at most 6 posts in all. The add's sign-in link is never printed, nor is the
token.

The add's answers. 200 goes on to the clean-up; the console not answering is `{"status": "not_running"}`
and a console without the account gates (409 `adding an account is not available on this host`) is
`{"status": "not_available"}`, both exit 75 with nothing else posted; a leftover profile of the same
name (409 `... already exists`, from a stopped earlier run) is cleaned up and the add posted once more,
a second one being not met; a 502 (`the account was added; its sign-in could not start`) is cleaned up
and then not met with the console's text; any other answer is not met with its status and text, nothing
having been created.

Outputs. One stdout line of JSON with sorted keys (the delegated reading prints its own); not met is
`{"reason": ..., "status": "not_met"}`. Exit 0 met, 1 not met, 75 not yet, 2 a bad argument. A clean-up
that cannot reach the console is 75, and the next run clears the leftover through the rule above; one the
console refuses is not met.
"""
from __future__ import annotations

import argparse
import contextlib
import http.client
import io
import json
import sys
import time
from collections.abc import Callable
from pathlib import Path
from urllib.parse import urlsplit

from agent_tools.console import account_add, capacity_check, manager_check
from agent_tools.project_contract import agent_platform

DEFAULT_URL = manager_check.DEFAULT_URL
DEFAULT_NAME = "zzcheck-mac"
NOT_YET = 75
TIMEOUT = 90.0
RETRY_SECONDS = 5
REMOVE_POSTS = 6
NOT_AVAILABLE_TEXT = "adding an account is not available on this host"
SIGNIN_FAILED_TEXT = "the account was added; its sign-in could not start"
BUSY_SUFFIX = "try again in a moment"
RUNNING_SUFFIX = "cancel it first"


class PageClient:
    """The console's page writes at one loopback base URL, with the guard's headers."""

    def __init__(self, url: str, token: str) -> None:
        parts = urlsplit(url)
        self.host, self.port, self.netloc = parts.hostname, parts.port, parts.netloc
        self.token = token

    def post(self, path: str, document: dict) -> tuple[int | None, str]:
        """The status and stripped text of one POST; `(None, ...)` when the console did not answer."""
        connection = http.client.HTTPConnection(self.host, self.port, timeout=TIMEOUT)
        try:
            connection.request("POST", path, body=json.dumps(document).encode(), headers={
                "Host": self.netloc, "Content-Type": "application/json",
                "Origin": f"http://{self.netloc}", "X-Console-Token": self.token})
            response = connection.getresponse()
            return response.status, response.read().decode("utf-8", "replace").strip()
        except (OSError, http.client.HTTPException):
            return None, "the console did not answer"
        finally:
            connection.close()


def reading(mode: str, after_seq: int, url: str) -> tuple[int, str]:
    """The watermarked page check of `mode` (`page-add` or `page-remove`): its exit and printed line."""
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = capacity_check.main([f"--{mode}", "--after-seq", str(after_seq),
                                    "--url", url + "/api/state"])
    return code, out.getvalue().strip()


def _name(text: str) -> str:
    if not account_add.NAME.fullmatch(text):
        raise argparse.ArgumentTypeError("not a valid account name")
    return text


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="page_account_check", description=__doc__.splitlines()[0])
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--page-add", action="store_const", const="page-add", dest="mode")
    mode.add_argument("--page-remove", action="store_const", const="page-remove", dest="mode")
    parser.add_argument("--after-seq", type=manager_check._positive, required=True,
                        help="read only log rows whose seq is above this")
    parser.add_argument("--url", type=manager_check._loopback_url, default=DEFAULT_URL)
    parser.add_argument("--token-file", type=Path, default=None)
    parser.add_argument("--name", type=_name, default=DEFAULT_NAME)
    return parser


def _finish(document: dict, code: int) -> int:
    manager_check._print(document)
    return code


def _not_met(reason: str) -> int:
    return _finish({"reason": reason, "status": "not_met"}, 1)


def _cleanup(client, name: str, sleep: Callable[[float], None]) -> int | None:
    """Cancel the profile's sign-in and remove it; None when removed, else the check's exit."""
    status, _ = client.post("/api/signin-cancel", {"profile": name})
    if status is None:
        return _finish({"status": "not_running"}, NOT_YET)
    for post in range(REMOVE_POSTS):
        status, text = client.post("/api/account-remove", {"profile": name, "typed": name})
        if status == 204:
            return None
        if status is None:
            return _finish({"status": "not_running"}, NOT_YET)
        if (status != 409 or not text.endswith((BUSY_SUFFIX, RUNNING_SUFFIX))
                or post == REMOVE_POSTS - 1):
            break
        sleep(RETRY_SECONDS)
    return _not_met(f"the throwaway profile {name} was not removed: {status} {text}")


def main(argv: list[str] | None = None, *, client=PageClient, read=reading,
         sleep: Callable[[float], None] = time.sleep) -> int:
    args = build_parser().parse_args(argv)
    code, line = read(args.mode, args.after_seq, args.url)
    if code == 0:
        print(line)
        return 0
    token_file = args.token_file or agent_platform.state_root() / "console" / "page-token"
    try:
        token = token_file.read_text(encoding="utf-8").strip()
    except (OSError, UnicodeDecodeError):
        return _finish({"status": "no_token"}, NOT_YET)
    page = client(args.url, token)
    name = args.name
    for attempt in (1, 2):
        status, text = page.post("/api/account-add", {"name": name})
        if status is None:
            return _finish({"status": "not_running"}, NOT_YET)
        if status == 200:
            break
        if status == 409 and text == NOT_AVAILABLE_TEXT:
            return _finish({"status": "not_available"}, NOT_YET)
        if status == 409 and text == f"account {name} already exists":
            if attempt == 2:
                return _not_met(f"the throwaway profile {name} could not be cleared")
            cleared = _cleanup(page, name, sleep)
            if cleared is not None:
                return cleared
            continue
        if status == 502 and text.startswith(SIGNIN_FAILED_TEXT):
            cleared = _cleanup(page, name, sleep)
            return _not_met(text) if cleared is None else cleared
        return _not_met(f"the add answered {status}: {text}")
    cleared = _cleanup(page, name, sleep)
    if cleared is not None:
        return cleared
    code, line = read(args.mode, args.after_seq, args.url)
    print(line)
    return code


if __name__ == "__main__":
    sys.exit(main())
