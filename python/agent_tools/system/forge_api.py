"""The GitHub transport: `gh api` calls, the forge's errors and generic issue and label operations.

Every call runs `gh` with `GITHUB_TOKEN` and `GH_TOKEN` removed from the child, so the keyring
credential answers. A failure raises `ForgeError`, whose `code` is gh_missing, gh_failed,
gh_timeout or payload_invalid.

Transport class (issue 740): `run_gh` marks a timeout, an HTTP 5xx and a connection failure
transient on the `ForgeError`; a caller may retry a whole idempotent operation on it.

The module reads no host clock: "now" is the server's `Date` header (D5).
"""
import json
import os
import re
import subprocess
from collections.abc import Iterable, Mapping, Sequence
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any
from urllib.parse import quote

HTTP_STATUS = re.compile(r"\(HTTP (\d{3})\)")
TRANSPORT = re.compile(
    r"\bHTTP 5\d\d\b|error connecting to|dial tcp|network is unreachable|connection refused"
    r"|connection reset|no such host|i/o timeout|TLS handshake timeout|unexpected EOF",
    re.IGNORECASE)
TIMEOUT = 30
DETAIL_LIMIT = 240


def is_transport(stderr: str) -> bool:
    """Whether a `gh` failure's stderr shows an HTTP 5xx or a connection failure."""
    return TRANSPORT.search(stderr) is not None


class ForgeError(Exception):
    """A forge call failed: `code` is gh_missing, gh_failed, gh_timeout or payload_invalid.

    `transient` is true for a transport error (issue 740 D2): a `gh_timeout`, or a `gh_failed`
    whose stderr shows HTTP 5xx or a connection failure."""

    def __init__(self, code: str, detail: str = "", transient: bool | None = None) -> None:
        super().__init__(f"{code}: {detail}" if detail else code)
        self.code = code
        self.detail = detail[:DETAIL_LIMIT]
        self.transient = code == "gh_timeout" if transient is None else bool(transient)


def run_gh(argv: list[str], allow: Iterable[int] = ()) -> tuple[int, str]:
    """Run `gh` without any token variable. Returns (0, stdout), or (status, stdout) when the
    call failed with an HTTP status in `allow`; every other failure is a ForgeError."""
    env = {k: v for k, v in os.environ.items() if k not in ("GITHUB_TOKEN", "GH_TOKEN")}
    try:
        done = subprocess.run(["gh", *argv], capture_output=True, text=True, timeout=TIMEOUT,
                              stdin=subprocess.DEVNULL, env=env)
    except subprocess.TimeoutExpired:
        raise ForgeError("gh_timeout", " ".join(argv)) from None
    except OSError as error:
        raise ForgeError("gh_missing", str(error)) from None
    if done.returncode == 0:
        return 0, done.stdout
    found = HTTP_STATUS.search(done.stderr)
    status = int(found[1]) if found else 0
    if status and status in set(allow):
        return status, done.stdout
    raise ForgeError("gh_failed", done.stderr.strip(), transient=is_transport(done.stderr))


def logged_in() -> bool:
    """Whether `gh` holds a credential: `gh auth status` succeeds. Any forge failure, a missing `gh` included, is False."""
    try:
        run_gh(["auth", "status"])
    except ForgeError:
        return False
    return True


def gh_json(argv: list[str], allow: Iterable[int] = ()) -> Any:
    """The parsed stdout of a `gh` call, or None when it failed with a status in `allow`."""
    status, out = run_gh(argv, allow)
    if status:
        return None
    try:
        return json.loads(out)
    except ValueError:
        raise ForgeError("payload_invalid", "stdout is not JSON") from None


def api_get(path: str, allow: Iterable[int] = ()) -> Any:
    """The parsed JSON of one `gh api` read, or None when it failed with a status in `allow`."""
    return gh_json(["api", path], allow)


def api_pages(path: str) -> list[Any]:
    """The parsed JSON page of every page of one paginated `gh api` read, in order."""
    pages = gh_json(["api", "--paginate", "--slurp", path])
    if not isinstance(pages, list):
        raise ForgeError("payload_invalid", "paginated listing is not an array of pages")
    return pages


def server_now() -> datetime:
    """The forge's current time: the `Date` header of a free `rate_limit` call (D5)."""
    _, out = run_gh(["api", "--include", "rate_limit"])
    headers = re.split(r"\r?\n\r?\n", out, maxsplit=1)[0].splitlines()
    for line in headers[1:]:
        name, _, value = line.partition(":")
        if name.strip().lower() == "date":
            try:
                parsed = parsedate_to_datetime(value.strip())
            except (TypeError, ValueError):
                break
            return (parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None
                    else parsed.astimezone(timezone.utc))
    raise ForgeError("payload_invalid", "no readable Date header")


def ensure_label(slug: str, name: str, color: str) -> None:
    """Create the label; HTTP 422 means it already exists (D7)."""
    run_gh(["api", "-X", "POST", f"repos/{slug}/labels", "-f", f"name={name}", "-f", f"color={color}"],
        allow=(422,))


def add_label(slug: str, issue: int, name: str) -> None:
    run_gh(["api", "-X", "POST", f"repos/{slug}/issues/{issue}/labels", "-f", f"labels[]={name}"])


def remove_label(slug: str, issue: int, name: str) -> None:
    """Remove the label; HTTP 404 means it is not there (D7)."""
    run_gh(["api", "-X", "DELETE", f"repos/{slug}/issues/{issue}/labels/{quote(name, safe='')}"],
        allow=(404,))


def graphql(query: str, variables: Mapping[str, str]) -> Any:
    """The parsed JSON of one `gh api graphql` call with string variables."""
    return gh_json(["api", "graphql", "-f", f"query={query}",
                  *(arg for key, value in variables.items() for arg in ("-f", f"{key}={value}"))])


def create_issue(slug: str, title: str, body: str, labels: Sequence[str] = ()) -> int:
    """Create an issue; its number."""
    created = gh_json(["api", "-X", "POST", f"repos/{slug}/issues", "-f", f"title={title}",
                     "-f", f"body={body}", *(arg for name in labels for arg in ("-f", f"labels[]={name}"))])
    number = created.get("number") if isinstance(created, dict) else None
    if isinstance(number, bool) or not isinstance(number, int):
        raise ForgeError("payload_invalid", "created issue has no number")
    return number


def add_blocked_by(slug: str, issue: int, blocker_id: int) -> None:
    """Record that `issue` is blocked by the issue whose database id is `blocker_id`."""
    run_gh(["api", "--method", "POST", f"repos/{slug}/issues/{issue}/dependencies/blocked_by",
         "-F", f"issue_id={blocker_id}"])


def list_issues(slug: str, label: str, since: datetime) -> list[dict]:
    """Every issue (any state) carrying `label` and updated since `since`, across all pages."""
    pages = api_pages(f"repos/{slug}/issues?labels={quote(label)}&state=all"
                      f"&since={since:%Y-%m-%dT%H:%M:%SZ}&per_page=100")
    if not all(isinstance(page, list) and all(isinstance(i, dict) for i in page) for page in pages):
        raise ForgeError("payload_invalid", "issues are not an array of objects")
    return [issue for page in pages for issue in page]


def open_issues(slug: str, label: str) -> list[dict]:
    """Every open issue (a pull request is not one) carrying `label`, across all pages."""
    pages = api_pages(f"repos/{slug}/issues?labels={quote(label)}&state=open&per_page=100")
    if not all(isinstance(page, list) and all(isinstance(i, dict) for i in page) for page in pages):
        raise ForgeError("payload_invalid", "issues are not an array of objects")
    return [issue for page in pages for issue in page if "pull_request" not in issue]


def close_issue(slug: str, issue: int, reason: str) -> None:
    """Close the issue with a state reason (`completed` or `not_planned`); closing a closed issue is a no-op."""
    run_gh(["api", "-X", "PATCH", f"repos/{slug}/issues/{issue}", "-f", "state=closed",
         "-f", f"state_reason={reason}"])
