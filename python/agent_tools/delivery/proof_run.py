"""The real-model proof run of the delivery engine on the fixture project.

    proof-run daily|now --platform-repo <o/n> --branch <b> --fixture <o/n> --fixture-branch <b>

`daily` proves the tip of the platform repository's branch `<b>` once: when that revision is the
latest one in the proven record, nothing runs (`unmoved`). `now` runs whatever the record says, so a
command starts one run at once from a reset fixture; both modes record alike. The revision is the
branch tip read through `gh`; the engine runs from `nix shell github:<o/n>/<revision>#agent-platform`
as `engine deliver <issue>` in the fixture's registered checkout, with no timeout of its own (the
engine's bounds apply). Every git child and the engine run without the variables that select a
repository (`SELECTORS`: `GIT_DIR`, `GIT_WORK_TREE` and the like), so an inherited one never aims a
check or the reset at another checkout.

One operation at a time: `prove` holds an exclusive non-blocking `flock` on `proof-run.lock` from
before it reads the branch tip and the proven record until after its last line; a held lock is `busy`
at once, with no tip read and no forge, git or engine call, so the revision proven is the tip as it
stood when the operation held the lock. The records live in the engine's state directory
(`~/.agents/state/engine`): `proof-runs.jsonl` (attempts) and `proven.jsonl` (proven revisions).

The fixed issue. A run delivers one issue, filed fresh by the run: `TITLE` and `BODY`, whose marker
`MARKER` is its last line. Before filing, the fixture is reset, after its checkout is checked. The
checkout must be the registered root, an absolute directory at the repository top level, whose
fetch and push `origin` URLs name the fixture repository on `github.com` by the adoption's own
origin rule, on the fixture branch; a failed check is a `Refusal` before any forge call or any
change to files or refs. Then each open pull request of the fixture that closes a marked open issue
is closed (its branch deleted), each open marked issue by a trusted author is closed as not
planned, and the checkout is fetched, hard-reset to `origin/<branch>`, cleaned and its worktrees
pruned, each of which must exit 0.

The attempt record. Once the lock is held and the branch tip is read, and before the registered
checkout is resolved or the fixture is touched, one line
`{"format": 1, "attempt": <uuid4 hex>, "event": "started", "mode", "project", "revision", "at"}`
(none when the daily revision is `unmoved`); after the engine exits, one line `{"format": 1,
"attempt", "event": "ended", "code", "end", "run", "issue", "at"}`. `end` and `run` come from the
engine's one result line on stdout and are `null` when stdout is not exactly one JSON object line. A
step that raises before the engine starts (the tip read, which records `started` with `revision`
`null` first; the registered checkout; the checkout check, a forge or git call of the reset, the
issue's creation) still ends the attempt, with `code` 2 and `end`, `run` and `issue` `null`, before
the error goes on, so a failed first scheduled attempt is never replaced by a later one.

The proven record. A line `{"format": 1, "issue", "project", "proven", "revision", "run"}` is
appended only when the engine exits 0 and its result line has `end == "done"`. Any other exit (3 a
stop, 1 a fault, 2, 4, or an unreadable result line) appends none and is `unproven`.
`latest_proven` is the revision of the last line that is an object of format 1 with a 40-character
lowercase hex revision; a torn or foreign line is skipped.

The filing pass. After `prove` has released its lock, every `daily` and `now` run that is not `busy`
(`unmoved` included) runs `bound_issues.file_pass` against `cleanup_issue.GitHubTracker(<platform
repo>)`: one issue per out-of-bounds engine step and per over-wide role bound. `proof-run file
--platform-repo <o/n>` runs only that pass and prints `{"filed": [...]}`, exit 0.

Output: one compact sorted-key line `{"action", "code", "end", "filed", "issue", "revision", "run"}` on
stdout, `action` one of `unmoved`, `busy`, `proven`, `unproven`, `filed` the numbers of the issues the
pass filed (`[]` for none, and for `busy`, which skips the pass). Exit 0 for `unmoved` and `proven`,
3 for `unproven`, 4 for `busy`. Exit 2 with stdout empty and one stderr line `proof-run: <reason>`
for a usage error, a `Refusal` or a `ForgeError`, a failure of the filing pass included, which comes
after the run's own effects (a proven line stays).

`proof-run observed --fixture <o/n> --activated <RFC 3339 UTC time>` reads, and writes nothing;
`--activated` is when the daemon was activated and is required. The attempt is the first `started`
line of the attempt record with `mode` `daily`, `project` the fixture and `at` at or after
`--activated` (a `now` attempt, or one that started earlier, never counts). It prints one compact
sorted-key line `{"attempt", "end", "issue", "run", "state"}` (the issue is the attempt's `ended`
line's, `null` while it runs) and exits 75 for `not_yet` (no such attempt) or `running` (no `ended`
line for it), 1 for `not_met` (its `ended` has `code` other than 0 or `end` other than `done`, or
ended more than three days after `--activated`, or the engine history has no line with the attempt's root `run`, the fixture, `end` `done` and the
attempt's issue, or no merged pull request of the fixture closes the issue), 0 for `met`, and 2 with
`proof-run: <reason>` on stderr for a `ForgeError`.
"""

from __future__ import annotations

import argparse
import fcntl
import json
import os
import re
import subprocess
import sys
import uuid
from collections.abc import Callable, Mapping, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import NamedTuple, Protocol

from agent_tools import canonical
from agent_tools.delivery import bound_issues, cleanup_issue, engine_housekeeping, engine_ledger
from agent_tools.delivery.cleanup_issue import Refusal
from agent_tools.project_contract import adopt_conformance
from agent_tools.system import forge_api

COMMAND = "proof-run"
FORMAT = 1
TITLE = "Log one more proof run"
MARKER = "<!-- agent:proof-run v1 -->"
BODY = (
    "Each proof run of the delivery engine leaves one line in `proof-runs.log` at the repository root.\n"
    "\n"
    "## What to build\n"
    "\n"
    "Append the line `issue <n>` to `proof-runs.log`, where `<n>` is this issue's number, creating the "
    "file when it is missing and keeping every line already there. Add a test to `test_proof_runs.py` "
    "(create it when missing, and keep every test already there) that fails unless `proof-runs.log` "
    "holds that line. Change no file other than these two.\n"
    "\n"
    "## Acceptance criteria\n"
    "\n"
    "- [ ] [code] `proof-runs.log` holds the line `issue <n>` for this issue's number, every earlier "
    "line kept — measured: the new test in `test_proof_runs.py`, run by the `Tests` check\n"
    "\n"
    f"{MARKER}\n")
REVISION = re.compile(r"[0-9a-f]{40}")
EXIT_UNPROVEN = 3
EXIT_BUSY = 4
EXIT_USAGE = 2
EXIT_NOT_YET = 75
OBSERVE_SECONDS = 3 * 24 * 60 * 60
GIT_STEPS = (("fetch", "--quiet", "origin"), ("reset", "--quiet", "--hard", "origin/{branch}"),
             ("clean", "-fdq"), ("worktree", "prune"))
ISSUE_QUERY = ("query($owner: String!, $name: String!, $after: String) {{ repository(owner: $owner, "
               "name: $name) {{ issue(number: {number}) {{ {state} closedByPullRequestsReferences("
               "first: 50, after: $after, includeClosedPrs: {closed}) {{ pageInfo {{ hasNextPage "
               "endCursor }} nodes {{ number {fields} repository {{ nameWithOwner }} }} }} }} }} }}")
# The variables that choose which repository a git child works in, never inherited by one.
SELECTORS = ("GIT_DIR", "GIT_WORK_TREE", "GIT_COMMON_DIR", "GIT_INDEX_FILE", "GIT_OBJECT_DIRECTORY",
             "GIT_ALTERNATE_OBJECT_DIRECTORIES", "GIT_NAMESPACE", "GIT_PREFIX")


class FixtureTracker(Protocol):
    def open_proof_issues(self) -> list[int]: ...

    def pulls_closing(self, issues: Sequence[int]) -> list[int]: ...

    def closed_by_merged_pull(self, issue: int) -> bool: ...

    def close_pull(self, number: int) -> None: ...

    def close_issue(self, number: int) -> None: ...

    def create(self, title: str, body: str) -> int: ...


class Outcome(NamedTuple):
    action: str
    revision: str | None
    issue: int | None
    run: str | None
    end: str | None
    code: int | None


def _closing_nodes(slug: str, issue: int, *, closed: bool) -> tuple[str | None, list[dict]]:
    """The issue's state and every closing pull request, all pages followed."""
    owner, name = slug.split("/", 1)
    query = ISSUE_QUERY.format(number=int(issue), closed="true" if closed else "false",
                               state="state" if closed else "",
                               fields="state merged" if closed else "state")
    cursors: set[str | None] = set()
    after: str | None = None
    state: str | None = None
    found_nodes: list[dict] = []
    while True:
        cursors.add(after)
        # `forge_api.graphql` sends every variable as text, so the first page leaves `after` out.
        variables = {"owner": owner, "name": name, **({} if after is None else {"after": after})}
        answer = forge_api.graphql(query, variables)
        data = answer.get("data") if isinstance(answer, dict) else None
        repository = data.get("repository") if isinstance(data, dict) else None
        found = repository.get("issue") if isinstance(repository, dict) else None
        references = found.get("closedByPullRequestsReferences") if isinstance(found, dict) else None
        nodes = references.get("nodes") if isinstance(references, dict) else None
        if not isinstance(nodes, list) or not all(isinstance(node, dict) for node in nodes):
            raise forge_api.ForgeError("payload_invalid", f"issue {issue} has no closing pull requests")
        if after is None:
            state = found.get("state") if isinstance(found.get("state"), str) else None
        found_nodes.extend(nodes)
        page = references.get("pageInfo")
        if not (isinstance(page, dict) and page.get("hasNextPage") is True):
            return state, found_nodes
        after = page.get("endCursor")
        if not isinstance(after, str) or after in cursors:
            raise forge_api.ForgeError("payload_invalid", f"issue {issue} has a page cursor that stalls")


def _belongs(node: dict, slug: str) -> bool:
    repository = node.get("repository")
    return isinstance(repository, dict) and repository.get("nameWithOwner") == slug


class GitHubFixture:
    def __init__(self, slug: str) -> None:
        self.slug = slug

    def open_proof_issues(self) -> list[int]:
        found = []
        for page in forge_api.api_pages(f"repos/{self.slug}/issues?state=open&per_page=100"):
            if not isinstance(page, list) or not all(isinstance(item, dict) for item in page):
                raise forge_api.ForgeError("payload_invalid", "issues are not an array of objects")
            for item in page:
                body, number = item.get("body"), item.get("number")
                if "pull_request" in item or not isinstance(body, str):
                    continue
                if not any(line.rstrip() == MARKER for line in body.splitlines()):
                    continue
                if not cleanup_issue.trusted(item):
                    continue
                if isinstance(number, bool) or not isinstance(number, int):
                    raise forge_api.ForgeError("payload_invalid", "an issue has no number")
                found.append(number)
        return found

    def pulls_closing(self, issues: Sequence[int]) -> list[int]:
        pulls: list[int] = []
        for issue in issues:
            _, nodes = _closing_nodes(self.slug, issue, closed=False)
            for node in nodes:
                number = node.get("number")
                if (node.get("state") == "OPEN" and _belongs(node, self.slug)
                        and isinstance(number, int)):
                    pulls.append(number)
        return pulls

    def closed_by_merged_pull(self, issue: int) -> bool:
        state, nodes = _closing_nodes(self.slug, issue, closed=True)
        return state == "CLOSED" and any(
            node.get("merged") is True and _belongs(node, self.slug) for node in nodes)

    def close_pull(self, number: int) -> None:
        forge_api.run_gh(["pr", "close", str(number), "--repo", self.slug, "--delete-branch"])

    def close_issue(self, number: int) -> None:
        forge_api.close_issue(self.slug, number, "not_planned")

    def create(self, title: str, body: str) -> int:
        return forge_api.create_issue(self.slug, title, body)


def proven_path() -> Path:
    return engine_housekeeping.engine_root() / "proven.jsonl"


def attempts_path() -> Path:
    return engine_housekeeping.engine_root() / "proof-runs.jsonl"


def lock_path() -> Path:
    return engine_housekeeping.engine_root() / "proof-run.lock"


def latest_proven(path: Path) -> str | None:
    try:
        data = Path(path).read_bytes()
    except FileNotFoundError:
        return None
    found = None
    for raw in data.split(b"\n"):
        try:
            line = json.loads(raw.decode("utf-8"))
        except (ValueError, RecursionError):
            continue
        revision = line.get("revision") if isinstance(line, dict) else None
        if (isinstance(line, dict) and line.get("format") == FORMAT and isinstance(revision, str)
                and REVISION.fullmatch(revision)):
            found = revision
    return found


def engine_argv(platform_repo: str, revision: str) -> list[str]:
    return ["nix", "shell", f"github:{platform_repo}/{revision}#agent-platform", "--command", "engine"]


def main_revision(platform_repo: str, branch: str) -> str:
    answer = forge_api.api_get(f"repos/{platform_repo}/branches/{branch}")
    commit = answer.get("commit") if isinstance(answer, dict) else None
    sha = commit.get("sha") if isinstance(commit, dict) else None
    if not isinstance(sha, str) or not REVISION.fullmatch(sha):
        raise forge_api.ForgeError("payload_invalid", f"branch {branch} has no 40-hex commit")
    return sha


def _without_selectors(env: Mapping[str, str] | None) -> dict[str, str]:
    """`env` (the process environment when `None`) without the variables that pick another repository."""
    return {key: value for key, value in (os.environ if env is None else env).items()
            if key not in SELECTORS}


def _git(root: Path, env: Mapping[str, str] | None, *args: str) -> subprocess.CompletedProcess:
    """`git <args>` run in `root` (its working directory, which is how a git wrapper keys a checkout)."""
    return subprocess.run(["git", *args], cwd=root, capture_output=True, text=True,
                          env=_without_selectors(env), stdin=subprocess.DEVNULL)


def checked_checkout(root: Path, slug: str, branch: str,
                     env: Mapping[str, str] | None = None) -> Path:
    """The checkout `root` when it is the fixture's own checkout on `branch`, else a `Refusal`."""
    checked = cleanup_issue.checked_root(str(root))
    answers: list[str | None] = []
    for arguments in (("get-url", "origin"), ("get-url", "--push", "--all", "origin")):
        done = _git(checked, env, "remote", *arguments)
        answers.extend((done.stdout.splitlines() or [None]) if done.returncode == 0 else [None])
    if not adopt_conformance.names_origin(answers, slug):
        raise Refusal(f"the remote origin of {checked} is not {slug}")
    current = _git(checked, env, "branch", "--show-current")
    if current.returncode != 0 or current.stdout.strip() != branch:
        raise Refusal(f"{checked} is not on branch {branch}")
    return checked


def reset_fixture(root: Path, *, slug: str, branch: str, tracker: FixtureTracker,
                  env: Mapping[str, str] | None = None) -> int:
    """Check the checkout, close every leftover proof pull and issue, reset it, file the fixed issue."""
    checked_checkout(root, slug, branch, env)
    leftover = tracker.open_proof_issues()
    for number in dict.fromkeys(tracker.pulls_closing(leftover)):
        tracker.close_pull(number)
    for number in leftover:
        tracker.close_issue(number)
    for step in GIT_STEPS:
        arguments = [argument.format(branch=branch) for argument in step]
        done = _git(root, env, *arguments)
        if done.returncode != 0:
            raise Refusal(f"git {' '.join(arguments)} failed in {root}: {done.stderr.strip()}")
    return tracker.create(TITLE, BODY)


def _stamp(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _result_line(stdout: str) -> dict | None:
    lines = stdout.splitlines()
    if len(lines) != 1:
        return None
    try:
        line = json.loads(lines[0])
    except (ValueError, RecursionError):
        return None
    return line if isinstance(line, dict) else None


def _string(line: dict | None, key: str) -> str | None:
    value = line.get(key) if line is not None else None
    return value if isinstance(value, str) else None


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def prove(tip: Callable[[], str], *, mode: str, root: Callable[[], Path], slug: str, branch: str,
          tracker: FixtureTracker, engine: Callable[[str], Sequence[str]], proven: Path,
          attempts: Path, lock: Path, env: Mapping[str, str] | None = None,
          now: Callable[[], datetime] = _utc_now) -> Outcome:
    """One attempt on the revision `tip()` names: the lock, the tip, the unmoved check, the reset, the engine.

    The tip is read once the lock is held, so the revision proven is the tip at the time the operation
    ran and never one an earlier caller read before another caller proved a newer one. `root()` names
    the fixture's checkout, read after the attempt is recorded. A tip that cannot be read records the
    attempt as started (revision `None`) and ended (code 2) before the error goes on; a revision found
    unmoved records no attempt.
    """
    def note(attempt: str, event: str, **fields: object) -> None:
        engine_housekeeping.append_history(
            {"format": FORMAT, "attempt": attempt, "event": event, **fields, "at": _stamp(now())},
            attempts)

    def failed(attempt: str) -> None:
        note(attempt, "ended", code=EXIT_USAGE, end=None, run=None, issue=None)

    engine_ledger.make_root(Path(lock).parent)
    descriptor = os.open(lock, os.O_RDWR | os.O_CREAT, 0o600)
    try:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return Outcome("busy", None, None, None, None, None)
        attempt = uuid.uuid4().hex
        try:
            revision = tip()
        except Exception:
            note(attempt, "started", mode=mode, project=slug, revision=None)
            failed(attempt)
            raise
        if mode == "daily" and latest_proven(proven) == revision:
            return Outcome("unmoved", revision, None, None, None, None)
        note(attempt, "started", mode=mode, project=slug, revision=revision)
        try:
            checkout = Path(root())
            issue = reset_fixture(checkout, slug=slug, branch=branch, tracker=tracker, env=env)
        except Exception:
            failed(attempt)
            raise
        try:
            done = subprocess.run([*engine(revision), "deliver", str(issue)], cwd=checkout,
                                  env=_without_selectors(env), stdout=subprocess.PIPE,
                                  text=True, stdin=subprocess.DEVNULL)
            code, stdout = done.returncode, done.stdout
        except OSError as error:
            sys.stderr.write(f"{COMMAND}: the engine did not start: {error}\n")
            code, stdout = 1, ""
        result = _result_line(stdout)
        end, run = _string(result, "end"), _string(result, "run")
        note(attempt, "ended", code=code, end=end, run=run, issue=issue)
        if code == 0 and end == "done":
            engine_housekeeping.append_history(
                {"format": FORMAT, "issue": issue, "project": slug, "proven": _stamp(now()),
                 "revision": revision, "run": run}, proven)
            return Outcome("proven", revision, issue, run, end, code)
        return Outcome("unproven", revision, issue, run, end, code)
    finally:
        os.close(descriptor)


class _Parser(argparse.ArgumentParser):
    def error(self, message: str):
        raise Refusal(message)


def parser() -> argparse.ArgumentParser:
    built = _Parser(prog=COMMAND, description="Prove the delivery engine on the fixture project.")
    built.add_argument("mode", choices=("daily", "now", "file", "observed"))
    for flag in ("--platform-repo", "--branch", "--fixture", "--fixture-branch", "--activated"):
        built.add_argument(flag)
    return built


def _json_lines(path: Path) -> list[dict]:
    try:
        data = Path(path).read_bytes()
    except FileNotFoundError:
        return []
    found = []
    for raw in data.split(b"\n"):
        try:
            line = json.loads(raw.decode("utf-8"))
        except (ValueError, RecursionError):
            continue
        if isinstance(line, dict):
            found.append(line)
    return found


def _seconds_between(start: object, end: object) -> float | None:
    try:
        return (canonical.parse_rfc3339_utc(end) - canonical.parse_rfc3339_utc(start)).total_seconds()
    except ValueError:
        return None


def _after(start: object, end: object) -> bool:
    """Whether `end` is a time at or after `start`."""
    seconds = _seconds_between(start, end)
    return seconds is not None and seconds >= 0


def observe(fixture: str, *, activated: str, attempts: Path, history: Path,
            tracker: FixtureTracker) -> tuple[int, dict]:
    """The exit code and result line of the first scheduled (`daily`) attempt on `fixture`; reads only.

    `activated` is the RFC 3339 UTC time the daemon was activated; the attempt is the first one that
    started at or after it, and it must end within `OBSERVE_SECONDS` of it.
    """
    first = next((line for line in _json_lines(attempts)
                  if line.get("format") == FORMAT and line.get("event") == "started"
                  and line.get("mode") == "daily" and line.get("project") == fixture
                  and _after(activated, line.get("at"))), None)
    if first is None:
        return EXIT_NOT_YET, {"attempt": None, "end": None, "issue": None, "run": None,
                              "state": "not_yet"}
    attempt = first.get("attempt")
    ended = next((line for line in _json_lines(attempts)
                  if line.get("format") == FORMAT and line.get("event") == "ended"
                  and line.get("attempt") == attempt), None)
    if ended is None:
        return EXIT_NOT_YET, {"attempt": attempt, "end": None, "issue": None, "run": None,
                              "state": "running"}
    end, run, issue = ended.get("end"), ended.get("run"), ended.get("issue")
    line = {"attempt": attempt, "end": end, "issue": issue, "run": run}
    took = _seconds_between(activated, ended.get("at"))
    met = (ended.get("code") == 0 and end == "done" and took is not None
           and 0 <= took <= OBSERVE_SECONDS
           and isinstance(run, str) and isinstance(issue, int) and not isinstance(issue, bool)
           and any(entry.get("run") == run and entry.get("project") == fixture
                   and entry.get("end") == "done" and entry.get("issue") == issue
                   for entry in _json_lines(history))
           and tracker.closed_by_merged_pull(issue))
    return (0, {**line, "state": "met"}) if met else (1, {**line, "state": "not_met"})


def _exit_of(outcome: Outcome) -> int:
    return {"unproven": EXIT_UNPROVEN, "busy": EXIT_BUSY}.get(outcome.action, 0)


def _file_pass(platform_repo: str) -> list[int]:
    filed = bound_issues.file_pass(
        cleanup_issue.GitHubTracker(platform_repo), engine_housekeeping.history_path(),
        bound_issues.seen_path(), bound_issues.lock_path(), _utc_now())
    return [item.issue for item in filed]


def _prove(args: argparse.Namespace) -> Outcome:
    missing = [flag for flag in ("branch", "fixture", "fixture_branch") if getattr(args, flag) is None]
    if missing:
        raise Refusal("the following arguments are required: "
                      + ", ".join("--" + flag.replace("_", "-") for flag in missing))
    for slug in (args.platform_repo, args.fixture):
        if not cleanup_issue.SLUG.fullmatch(slug):
            raise Refusal(f"not <owner>/<name>: {slug}")
    return prove(
        lambda: main_revision(args.platform_repo, args.branch), mode=args.mode,
        root=lambda: Path(cleanup_issue.registered_root(args.fixture)),
        slug=args.fixture, branch=args.fixture_branch, tracker=GitHubFixture(args.fixture),
        engine=lambda revision: engine_argv(args.platform_repo, revision),
        proven=proven_path(), attempts=attempts_path(), lock=lock_path(), env=dict(os.environ))


def main(argv: list[str] | None = None) -> int:
    try:
        args = parser().parse_args(argv)
        if args.mode == "observed":
            if args.fixture is None:
                raise Refusal("the following arguments are required: --fixture")
            if not cleanup_issue.SLUG.fullmatch(args.fixture):
                raise Refusal(f"not <owner>/<name>: {args.fixture}")
            if args.activated is None:
                raise Refusal("the following arguments are required: --activated")
            try:
                canonical.parse_rfc3339_utc(args.activated)
            except ValueError:
                raise Refusal(f"--activated is not an RFC 3339 UTC time: {args.activated}") from None
            code, line = observe(args.fixture, activated=args.activated, attempts=attempts_path(),
                                 history=engine_housekeeping.history_path(),
                                 tracker=GitHubFixture(args.fixture))
            print(json.dumps(line, sort_keys=True, separators=(",", ":")))
            return code
        if args.platform_repo is None:
            raise Refusal("the following arguments are required: --platform-repo")
        if not cleanup_issue.SLUG.fullmatch(args.platform_repo):
            raise Refusal(f"not <owner>/<name>: {args.platform_repo}")
        if args.mode == "file":
            print(json.dumps({"filed": _file_pass(args.platform_repo)}, sort_keys=True,
                             separators=(",", ":")))
            return 0
        outcome = _prove(args)
        filed = [] if outcome.action == "busy" else _file_pass(args.platform_repo)
    except (Refusal, forge_api.ForgeError) as error:
        print(f"{COMMAND}: {' '.join(str(error).split())}", file=sys.stderr)
        return EXIT_USAGE
    print(json.dumps({**outcome._asdict(), "filed": filed}, sort_keys=True, separators=(",", ":")))
    return _exit_of(outcome)


if __name__ == "__main__":
    sys.exit(main())
