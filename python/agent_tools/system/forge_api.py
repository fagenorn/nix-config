"""The GitHub transport: `gh api` calls, the forge's errors and generic issue and label operations.

Every call runs `gh` with `GITHUB_TOKEN` and `GH_TOKEN` removed from the child, so the keyring
credential answers. A failure raises `ForgeError`, whose `code` is gh_missing, gh_failed,
gh_timeout or payload_invalid.

Transport class (issue 740): `run_gh` marks a timeout, an HTTP 5xx and a connection failure
transient on the `ForgeError`; a caller may retry a whole idempotent operation on it.

Deadline (issue 1075): `deadline(at, clock)` bounds the `run_gh` calls made in its block, in the
current thread. Each call starts only while `clock() < at` and runs with `timeout=min(TIMEOUT,
at - clock())`; a call at or past `at` raises the transient `ForgeError("gh_timeout", "deadline
passed: ...")` without starting `gh`. The innermost block wins and leaving it restores the outer one.

Cancellation (issue 1110): `run_gh` and `gh_json` take an optional `cancelled` test. With one, the
call runs `gh` in its own process group and asks the test every `CANCEL_POLL_SECONDS`; once it is true
the group is killed and the call raises `ForgeError("cancelled")`, so a caller closing does not wait
out the transport timeout. Without one a call is a plain `subprocess.run`.

The module reads no host clock: "now" is the server's `Date` header (D5). The one exception is the
`clock` a caller hands to `deadline`, which is the only clock the module ever reads.
"""
import contextlib
import contextvars
import json
import os
import re
import signal
import subprocess
import time
from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence
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
CANCEL_POLL_SECONDS = 0.2
DETAIL_LIMIT = 240
_DEADLINE: contextvars.ContextVar[tuple[float, Callable[[], float]] | None] = contextvars.ContextVar(
    "forge_api_deadline", default=None)


@contextlib.contextmanager
def deadline(at: float, clock: Callable[[], float]) -> Iterator[None]:
    """Bound every `run_gh` call of this block, in this thread, to end by `at` on `clock`."""
    token = _DEADLINE.set((at, clock))
    try:
        yield
    finally:
        _DEADLINE.reset(token)


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


def _run_cancellable(command: list[str], timeout: float, env: dict[str, str],
                     cancelled: Callable[[], bool]) -> subprocess.CompletedProcess:
    """`subprocess.run` for `command` in its own group, ended whole by `cancelled()` or `timeout`."""
    with subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                          stderr=subprocess.PIPE, text=True, env=env,
                          start_new_session=True) as process:
        end = time.monotonic() + timeout
        while True:
            left = end - time.monotonic()
            if cancelled() or left <= 0:
                with contextlib.suppress(ProcessLookupError):
                    os.killpg(process.pid, signal.SIGKILL)
                process.communicate()
                if cancelled():
                    raise ForgeError("cancelled")
                raise subprocess.TimeoutExpired(command, timeout)
            try:
                out, err = process.communicate(timeout=min(left, CANCEL_POLL_SECONDS))
            except subprocess.TimeoutExpired:
                continue
            return subprocess.CompletedProcess(command, process.returncode, out, err)


def run_gh(argv: list[str], allow: Iterable[int] = (),
           cancelled: Callable[[], bool] | None = None, cli: str = "gh") -> tuple[int, str]:
    """Run `gh` (or the GitHub CLI wrapper `cli`) without any token variable. Returns (0, stdout), or (status, stdout) when the
    call failed with an HTTP status in `allow`; every other failure is a ForgeError. A true
    `cancelled()` ends the call at once with `ForgeError("cancelled")`."""
    env = {k: v for k, v in os.environ.items() if k not in ("GITHUB_TOKEN", "GH_TOKEN")}
    timeout = TIMEOUT
    bound = _DEADLINE.get()
    if bound is not None:
        left = bound[0] - bound[1]()
        if left <= 0:
            raise ForgeError("gh_timeout", "deadline passed: " + " ".join(argv))
        timeout = min(TIMEOUT, left)
    try:
        if cancelled is None:
            done = subprocess.run([cli, *argv], capture_output=True, text=True, timeout=timeout,
                                  stdin=subprocess.DEVNULL, env=env)
        else:
            done = _run_cancellable([cli, *argv], timeout, env, cancelled)
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


def gh_json(argv: list[str], allow: Iterable[int] = (),
            cancelled: Callable[[], bool] | None = None, cli: str = "gh") -> Any:
    """The parsed stdout of a `gh` call, or None when it failed with a status in `allow`."""
    status, out = run_gh(argv, allow, cancelled, cli)
    if status:
        return None
    try:
        return json.loads(out)
    except ValueError:
        raise ForgeError("payload_invalid", "stdout is not JSON") from None


def api_get(path: str, allow: Iterable[int] = (), cli: str = "gh") -> Any:
    """The parsed JSON of one `gh api` read, or None when it failed with a status in `allow`."""
    return gh_json(["api", path], allow, cli=cli)


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
