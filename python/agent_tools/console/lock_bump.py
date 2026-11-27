"""`lock_bump`: one pass that offers a proven revision to one project as a lock bump pull request.

The record `~/.agents/state/console/lock-bumps.json` is `{"format": 1, "projects": {<project>: {"revision",
"pull", "outcome": "open"|"merged"|"red"|"closed", "issue", "from", "commit"}}}` for the last bump of each project; an
absent file is empty and an unreadable or malformed one is `BumpRefused`, never reset. Open bumps are read
from the forge each pass. The pass takes only the registry entry whose `project_id` is `project`. Order:
every open bump of another revision is closed (`replaced`); an open bump of `latest` is settled by its
required checks (`merged` on green only when its head is the recorded built commit and the lock there pins
`latest`, else `unverified`; `filed` once and then `red_known` on red, `pending`); a revision whose
record is not open is `done` and never opened again, so the next proven revision is the retry; otherwise
a lock that is behind `latest` gets one built branch and one pull request (`opened`). The record is written
after each forge write. A red bump is never merged or closed by the pass before a newer revision arrives,
even when a later reading is green. The red outcome is recorded before its issue is filed, and a red record
with no issue gets one on a later pass. Before it files, the pass looks for an issue by its own account
carrying that project-and-revision marker in the platform repository, so a lost answer files no second
issue and another author's marker is ignored. `commit` is
the built commit of the bump, or null for a bump found open with no record.

`Bumper` is the console's pass: it reads the registry and the latest proven revision, runs `bump_pass` and
prints one `console: lock_bump <project> <action> <revision> <pull> <issue>` line per step, or one
`console: lock_bump_failed` line when the pass is refused. `start` runs it in a daemon thread every ten
minutes until its stop event is set, and that event is the pass's `cancel`.

`python -m agent_tools.console.lock_bump observed --repo O/N --base BRANCH (--since STAMP [--within-days 7] |
--merge SHA --platform-repo O/N [--store FILE]) [--proven FILE]` is the evidence check, judged on the pull
request's required contexts as the merge does, and met only when the lock of the merged tree pins the revision.
With `--since` the revision is the first line of the proven record stamped at or after `STAMP` (the activation,
`YYYY-MM-DDTHH:MM:SSZ`); the pull request is the one merged into `BRANCH` from that revision's
`lock-bump-<revision>` branch within the days after `STAMP`. With `--merge` the activation is the first
successful one in the console's event store (`--store`) whose commit holds the platform commit `SHA`, and the
pull request is the first merged into `BRANCH` after it, in order of merge, from the `lock-bump-<revision>`
branch of a proven revision that holds `SHA`, within the seven days after it. It prints one JSON line and
exits 0 met, 1 not met (red, a lock that does not pin the revision, or a merge past the window or, with
`--since`, no merge by then), 75 not yet, 2 on a forge, store or record error.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import sys
import tempfile
import threading
from datetime import datetime, timedelta, timezone
from collections.abc import Callable, Collection, Mapping, Sequence
from pathlib import Path
from typing import NamedTuple, Protocol, TextIO

from agent_tools.console import activation_check, approve, service
from agent_tools.console import lock_bump_forge
from agent_tools.console.lock_bump_forge import Checks, GitHubBumpForge, OpenBump
from agent_tools.console.lock_bump_tree import BumpRefused, Built, GitBuilder, branch_for, revision_of_branch
from agent_tools.delivery import proof_run
from agent_tools.project_contract import agent_platform
from agent_tools.system import forge_api

FORMAT = 1
LOCK_BUMP_SECONDS = 600.0
LOCK_BUMP_THREAD = "console-lock-bump"
MARKER = "<!-- agent:lock-bump v1 -->"
WITHIN_DAYS = 7
STAMP = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z")
OUTCOMES = frozenset(("open", "merged", "red", "closed"))
REVISION = re.compile(r"[0-9a-f]{40}")


class Step(NamedTuple):
    project: str
    action: str
    revision: str | None
    pull: int | None
    issue: int | None
    detail: str | None


class BumpForge(Protocol):
    def open_bumps(self, slug: str, base: str, cancel: threading.Event | None = None) -> list[OpenBump]: ...

    def checks(self, slug: str, number: int, cancel: threading.Event | None = None) -> Checks: ...

    def open_pull(self, slug: str, branch: str, base: str, title: str, body: str,
                  cancel: threading.Event | None = None) -> int: ...

    def merge(self, slug: str, number: int, head: str, cancel: threading.Event | None = None) -> None: ...

    def close(self, slug: str, number: int, branch: str, cancel: threading.Event | None = None) -> None: ...

    def compare(self, repo: str, base: str, head: str, cancel: threading.Event | None = None) -> str: ...


class Tracker(Protocol):
    def create(self, title: str, body: str) -> int: ...

    def find(self, project: str, revision: str) -> int | None: ...


class Builder(Protocol):
    def pin(self, root: Path, slug: str, base: str, cancel: threading.Event | None = None) -> str: ...

    def build(self, root: Path, slug: str, base: str, revision: str,
              cancel: threading.Event | None = None) -> Built: ...

    def verify(self, root: Path, slug: str, revision: str, head: str,
               cancel: threading.Event | None = None) -> None: ...


def default_state_path() -> Path:
    return agent_platform.state_root() / "console" / "lock-bumps.json"


def _number(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _valid_record(record: object) -> bool:
    return (isinstance(record, dict) and set(record) == {"revision", "pull", "outcome", "issue", "from", "commit"}
            and isinstance(record["revision"], str) and REVISION.fullmatch(record["revision"]) is not None
            and _number(record["pull"]) and record["pull"] > 0 and record["outcome"] in OUTCOMES
            and (record["issue"] is None or _number(record["issue"]))
            and (record["from"] is None or (isinstance(record["from"], str)
                                            and REVISION.fullmatch(record["from"]) is not None))
            and (record["commit"] is None or (isinstance(record["commit"], str)
                                              and REVISION.fullmatch(record["commit"]) is not None)))


def read_state(path: Path) -> dict:
    try:
        raw = Path(path).read_bytes()
    except FileNotFoundError:
        return {"format": FORMAT, "projects": {}}
    except OSError as error:
        raise BumpRefused(f"the lock bump record cannot be read: {error}") from None
    try:
        state = json.loads(raw.decode("utf-8"))
    except (ValueError, RecursionError):
        raise BumpRefused("the lock bump record is not JSON") from None
    projects = state.get("projects") if isinstance(state, dict) else None
    if (not isinstance(state, dict) or state.get("format") != FORMAT or not isinstance(projects, dict)
            or set(state) != {"format", "projects"}
            or not all(_valid_record(record) for record in projects.values())):
        raise BumpRefused("the lock bump record is malformed")
    return state


def write_state(path: Path, state: dict) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(dir=path.parent, prefix=".lock-bumps-")
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            stream.write(json.dumps(state, indent=2, sort_keys=True) + "\n")
        os.replace(temporary, path)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise


def _pull_text(platform_repo: str, latest: str, pin: str) -> tuple[str, str]:
    body = (f"This moves the platform lock to {platform_repo}@{latest}, a proven revision, from {pin}.\n\n"
            "The console merges it once every required check is green.\n\n" + MARKER)
    return f"Bump the agent platform to {latest[:12]}", body


def red_marker(project: str, revision: str) -> str:
    return f"<!-- agent:lock-bump-red v1 {project} {revision} -->"


def _issue_text(project: str, latest: str, pull: int, failing: Sequence[str]) -> tuple[str, str]:
    checks = ", ".join(failing)
    body = (f"The lock bump of {project} to {latest} fails: {checks}.\n\n"
            f"Pull request: https://github.com/{project}/pull/{pull}\n\n"
            + "\n".join(f"- {name}" for name in failing)
            + "\n\nOnly the lock changed, so the failure is the platform's. The project stays on its old "
              "lock until the next proven revision is offered.\n\n" + red_marker(project, latest))
    return f"Lock bump to {latest[:12]} fails {checks} on {project}", body


def bump_pass(entries: Sequence[Mapping], *, project: str, base: str, platform_repo: str, latest: str | None,
              forge: BumpForge, tracker: Tracker, builder: Builder, state_path: Path,
              cancel: threading.Event | None = None) -> list[Step]:
    matching = [entry for entry in entries if entry.get("project_id") == project]
    if not matching:
        return [Step(project, "unregistered", None, None, None, None)]
    if latest is None:
        return [Step(project, "no_proven", None, None, None, None)]
    state = read_state(state_path)
    record = state["projects"].get(project)
    root = Path(matching[0]["root"])

    def save(new: dict | None) -> None:
        nonlocal record
        record = new
        if new is not None:
            state["projects"][project] = new
            write_state(state_path, state)

    def step(action: str, pull: int | None = None, issue: int | None = None, detail: str | None = None) -> Step:
        return Step(project, action, latest, pull, issue, detail)

    steps = []
    open_bumps = forge.open_bumps(project, base, cancel)
    for bump in open_bumps:
        if bump.revision != latest:
            forge.close(project, bump.number, branch_for(bump.revision), cancel)
            if record is not None and record["revision"] == bump.revision and record["outcome"] == "open":
                save({**record, "outcome": "closed"})
            steps.append(Step(project, "replaced", bump.revision, bump.number, None, None))
    current = [bump for bump in open_bumps if bump.revision == latest]
    if current:
        number = current[0].number
        if record is None or record["revision"] != latest:
            save({"revision": latest, "pull": number, "outcome": "open", "issue": None, "from": None,
                  "commit": None})
        return steps + [_settle(project, latest, number, record, forge, tracker, builder, root, save, cancel)]
    if record is not None and record["revision"] == latest:
        number = record["pull"]
        if record["outcome"] != "open":
            return steps + [step("done", number, record["issue"])]
        ended = forge.checks(project, number, cancel)
        if ended.state in ("merged", "closed"):
            save({**record, "outcome": ended.state})
            return steps + [step("ended", number, record["issue"], ended.state)]
        return steps + [step("pending", number)]
    pin = builder.pin(root, project, base, cancel=cancel)
    if pin == latest:
        return steps + [step("current")]
    status = forge.compare(platform_repo, pin, latest, cancel)
    if status != "ahead":
        return steps + [step("not_behind", detail=status)]
    built = builder.build(root, project, base, latest, cancel=cancel)
    title, body = _pull_text(platform_repo, latest, pin)
    number = forge.open_pull(project, built.branch, base, title, body, cancel)
    save({"revision": latest, "pull": number, "outcome": "open", "issue": None, "from": pin,
          "commit": built.commit})
    return steps + [step("opened", number)]


def _settle(project, latest, number, record, forge, tracker, builder, root, save, cancel) -> Step:
    checks = forge.checks(project, number, cancel)
    if checks.state in ("merged", "closed"):
        save({**record, "outcome": checks.state})
        return Step(project, "ended", latest, number, record["issue"], checks.state)
    if record["outcome"] == "red":
        if record["issue"] is not None:
            return Step(project, "red_known", latest, number, record["issue"], None)
        return _report(project, latest, number, record, checks.failing, tracker, save)
    if checks.state == "green":
        if record["commit"] is not None and checks.head != record["commit"]:
            return Step(project, "unverified", latest, number, record["issue"], "head moved")
        try:
            builder.verify(root, project, latest, checks.head, cancel)
        except BumpRefused as error:
            return Step(project, "unverified", latest, number, record["issue"], str(error))
        forge.merge(project, number, checks.head, cancel)
        save({**record, "outcome": "merged"})
        return Step(project, "merged", latest, number, record["issue"], None)
    if checks.state == "red":
        red = {**record, "outcome": "red"}
        save(red)
        return _report(project, latest, number, red, checks.failing, tracker, save)
    return Step(project, "pending", latest, number, record["issue"], None)


def _report(project, latest, number, red, failing, tracker, save) -> Step:
    """The red issue of a bump already recorded red: the one on the tracker, else a new one, then recorded."""
    known = tracker.find(project, latest)
    issue = known if known is not None else tracker.create(
        *_issue_text(project, latest, number, failing or ("a required check",)))
    save({**red, "issue": issue})
    return Step(project, "red_known" if known is not None else "filed", latest, number, issue, None)


def _account_login() -> object:
    user = forge_api.api_get("user")
    return user.get("login") if isinstance(user, dict) else None


class PlatformTracker:
    def __init__(self, platform_repo: str, *, pages: Callable[[str], list] = forge_api.api_pages,
                 create: Callable[[str, str, str], int] = forge_api.create_issue,
                 author: Callable[[], object] = lambda: _account_login()):
        self._platform_repo = platform_repo
        self._pages = pages
        self._create = create
        self._author = author

    def create(self, title: str, body: str) -> int:
        return self._create(self._platform_repo, title, body)

    def find(self, project: str, revision: str) -> int | None:
        """The number of an issue of the platform repository, filed by the account this pass runs as, that
        carries the red marker of this bump."""
        marker = red_marker(project, revision)
        login = self._author()
        if not isinstance(login, str) or not login:
            raise forge_api.ForgeError("payload_invalid", "the account the pass runs as has no login")
        for page in self._pages(f"repos/{self._platform_repo}/issues?state=all&per_page=100"):
            for issue in page if isinstance(page, list) else []:
                if not isinstance(issue, dict) or "pull_request" in issue:
                    continue
                number, body, user = issue.get("number"), issue.get("body"), issue.get("user")
                filed_by = user.get("login") if isinstance(user, dict) else None
                if (isinstance(body, str) and marker in body.splitlines() and isinstance(number, int)
                        and not isinstance(number, bool) and isinstance(filed_by, str)
                        and filed_by.casefold() == login.casefold()):
                    return number
        return None


def _line(step: Step) -> str:
    fields = [step.project, step.action, step.revision[:12] if step.revision else "-",
              "-" if step.pull is None else str(step.pull), "-" if step.issue is None else str(step.issue)]
    return "console: lock_bump " + " ".join(fields) + (f" {step.detail}" if step.detail else "")


class Bumper:
    def __init__(self, project: str, branch: str, platform_repo: str, *, forge: BumpForge | None = None,
                 tracker: Tracker | None = None, builder: Builder | None = None,
                 registry: Callable[[], list[dict]] = agent_platform.read_registry,
                 latest: Callable[[], str | None] | None = None, state_path: Path | None = None,
                 out: TextIO | None = None):
        self._project = project
        self._branch = branch
        self._platform_repo = platform_repo
        self._forge = forge or GitHubBumpForge()
        self._tracker = tracker or PlatformTracker(platform_repo)
        self._builder = builder or GitBuilder(platform_repo)
        self._registry = registry
        self._latest = latest or (lambda: proof_run.latest_proven(proof_run.proven_path()))
        self._state_path = state_path
        self._out = out

    def __call__(self, cancel: threading.Event) -> list[Step]:
        out = self._out or sys.stderr
        try:
            entries = self._registry()
            steps = bump_pass(
                entries, project=self._project, base=self._branch, platform_repo=self._platform_repo,
                latest=self._latest(), forge=self._forge, tracker=self._tracker, builder=self._builder,
                state_path=self._state_path or default_state_path(), cancel=cancel)
        except approve.Cancelled:
            return []
        except (BumpRefused, forge_api.ForgeError, agent_platform.PlatformManifestError) as error:
            print(f"console: lock_bump_failed {self._project} {type(error).__name__}: {error}", file=out)
            return []
        for step in steps:
            print(_line(step), file=out)
        return steps


def run_loop(bumper: Callable[[threading.Event], object], stop: threading.Event,
             seconds: float = LOCK_BUMP_SECONDS) -> None:
    while True:
        try:
            bumper(stop)
        except Exception as error:
            print(f"console: lock_bump_loop_failed {type(error).__name__}: {error}", file=sys.stderr)
        if stop.wait(seconds):
            return


def start(bumper: Callable[[threading.Event], object], stop: threading.Event,
          seconds: float = LOCK_BUMP_SECONDS) -> threading.Thread:
    thread = threading.Thread(target=run_loop, args=(bumper, stop, seconds), name=LOCK_BUMP_THREAD, daemon=True)
    thread.start()
    return thread


def _moment(stamp: str) -> datetime:
    return datetime.strptime(stamp, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


def _proven_lines(proven: Path) -> list[tuple[str, str]]:
    """The (revision, stamp) of every valid line of the proven record, in order; a missing record is empty."""
    try:
        data = Path(proven).read_bytes()
    except FileNotFoundError:
        return []
    found = []
    for raw in data.split(b"\n"):
        try:
            line = json.loads(raw.decode("utf-8"))
        except (ValueError, RecursionError):
            continue
        if not isinstance(line, dict) or line.get("format") != proof_run.FORMAT:
            continue
        revision, stamp = line.get("revision"), line.get("proven")
        if (isinstance(revision, str) and REVISION.fullmatch(revision) and isinstance(stamp, str)
                and STAMP.fullmatch(stamp)):
            found.append((revision, stamp))
    return found


def first_proven_after(proven: Path, since: str) -> str | None:
    """The revision of the first line of the proven record stamped at or after `since`, else None."""
    return next((revision for revision, stamp in _proven_lines(proven) if stamp >= since), None)


def _merged_bumps(repo: str, base: str, pages: Callable[[str], list],
                  revisions: Collection[str]) -> list[tuple[str, int, str, str]]:
    """The (merged_at, number, revision, merge commit) of every closed pull request of `repo` that merged a
    `lock-bump-<revision>` branch of one of `revisions` from `repo` itself into `base`."""
    merged = []
    for page in pages(f"repos/{repo}/pulls?state=closed&per_page=100"):
        for pull in page if isinstance(page, list) else []:
            if not isinstance(pull, dict):
                continue
            head = pull.get("head") if isinstance(pull.get("head"), dict) else {}
            target = pull.get("base") if isinstance(pull.get("base"), dict) else {}
            source = head.get("repo") if isinstance(head.get("repo"), dict) else {}
            sha, number, at = head.get("sha"), pull.get("number"), pull.get("merged_at")
            tree, revision = pull.get("merge_commit_sha"), revision_of_branch(head.get("ref"))
            if (isinstance(at, str) and STAMP.fullmatch(at) and revision is not None and revision in revisions
                    and target.get("ref") == base and source.get("full_name") == repo and isinstance(sha, str)
                    and approve.COMMIT.fullmatch(sha) and isinstance(number, int) and not isinstance(number, bool)
                    and isinstance(tree, str) and approve.COMMIT.fullmatch(tree)):
                merged.append((at, number, revision, tree))
    return merged


def observe(repo: str, *, base: str, since: str, proven: Path, pages: Callable[[str], list],
            verdict: Callable[[str, int], Checks], pinned: Callable[[str, str], str | None],
            now: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
            within_days: int = WITHIN_DAYS) -> tuple[int, dict]:
    """The exit code and printed record of the bump of the first proven revision after `since`, merged into
    `base` within `within_days`, whose merged lock pins that revision, judged on its required contexts."""
    deadline = _moment(since) + timedelta(days=within_days)
    revision = first_proven_after(proven, since)
    late = now() > deadline
    if revision is None:
        return (1, {"pull": None, "state": "not_met"}) if late else (75, {"pull": None, "state": "not_yet"})
    merged = _merged_bumps(repo, base, pages, {revision})
    if not merged:
        return (1, {"pull": None, "state": "not_met"}) if late else (75, {"pull": None, "state": "not_yet"})
    at, number, revision, tree = min(merged)
    if _moment(at) > deadline:
        return 1, {"pull": number, "state": "not_met"}
    return _judged(repo, number, revision, tree, verdict, pinned)


def _judged(repo: str, number: int, revision: str, tree: str, verdict: Callable[[str, int], Checks],
            pinned: Callable[[str, str], str | None]) -> tuple[int, dict]:
    """Met when the lock of the merged tree pins `revision` and the pull's required contexts are green."""
    if pinned(repo, tree) == revision and verdict(repo, number).state == "green":
        return 0, {"pull": number, "state": "met"}
    return 1, {"pull": number, "state": "not_met"}


def activated_at(rows: Sequence[tuple[str, Mapping]], merge: str,
                 contains: Callable[[str, str], bool | None]) -> datetime | None:
    """When the first successful activation in the console's (`at`, payload) rows whose commit holds `merge`
    finished, else None; an activation whose containment is undecided does not count."""
    for at, payload in rows:
        commit = payload.get("commit")
        if payload.get("ok") is not True or not isinstance(commit, str) or not contains(merge, commit):
            continue
        try:
            moment = datetime.fromisoformat(at)
        except ValueError:
            continue
        return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)
    return None


def observe_merged(repo: str, *, base: str, merge: str, platform_repo: str, proven: Path,
                   activated: datetime | None, pages: Callable[[str], list],
                   verdict: Callable[[str, int], Checks], compare: Callable[[str, str, str], str],
                   pinned: Callable[[str, str], str | None]) -> tuple[int, dict]:
    """The exit code and printed record of the first bump merged after `activated`, in order of merge, of a proven
    revision that holds the platform commit `merge`: not met when merged more than `WITHIN_DAYS` days after
    `activated`, else judged as `observe` does. No activation yet is not yet."""
    not_yet = (75, {"pull": None, "state": "not_yet"})
    revisions = {revision for revision, _ in _proven_lines(proven)}
    if not revisions or activated is None:
        return not_yet
    for at, number, revision, tree in sorted(_merged_bumps(repo, base, pages, revisions)):
        if _moment(at) < activated or compare(platform_repo, merge, revision) not in ("ahead", "identical"):
            continue
        if _moment(at) > activated + timedelta(days=WITHIN_DAYS):
            return 1, {"pull": number, "state": "not_met"}
        return _judged(repo, number, revision, tree, verdict, pinned)
    return not_yet


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="lock_bump", description="Check that a lock bump merged green.")
    modes = parser.add_subparsers(dest="mode", required=True)
    observed = modes.add_parser("observed")
    observed.add_argument("--repo", required=True, metavar="O/N")
    observed.add_argument("--base", required=True, metavar="BRANCH")
    form = observed.add_mutually_exclusive_group(required=True)
    form.add_argument("--since", metavar="STAMP")
    form.add_argument("--merge", metavar="SHA")
    observed.add_argument("--platform-repo", metavar="O/N")
    observed.add_argument("--within-days", type=int, default=None)
    observed.add_argument("--proven", type=Path, default=None, metavar="FILE")
    observed.add_argument("--store", type=Path, default=None, metavar="FILE")
    args = parser.parse_args(argv)
    owner_name = r"[A-Za-z0-9._-]+/[A-Za-z0-9._-]+"
    if re.fullmatch(owner_name, args.repo) is None:
        parser.error("--repo is owner/name")
    if args.since is not None:
        if STAMP.fullmatch(args.since) is None:
            parser.error("--since is YYYY-MM-DDTHH:MM:SSZ")
        if args.platform_repo is not None:
            parser.error("--platform-repo goes with --merge")
        if args.store is not None:
            parser.error("--store goes with --merge")
        within_days = WITHIN_DAYS if args.within_days is None else args.within_days
        if within_days < 1:
            parser.error("--within-days is a positive number")
    else:
        if REVISION.fullmatch(args.merge) is None:
            parser.error("--merge is 40 lowercase hex")
        if args.platform_repo is None or re.fullmatch(owner_name, args.platform_repo) is None:
            parser.error("--merge needs --platform-repo O/N")
        if args.within_days is not None:
            parser.error("--within-days goes with --since")
    proven, forge = args.proven or proof_run.proven_path(), lock_bump_forge.GitHubBumpForge()
    try:
        if args.since is not None:
            code, record = observe(args.repo, base=args.base, since=args.since, proven=proven,
                                   pages=forge_api.api_pages, verdict=forge.verdict, pinned=forge.pinned,
                                   within_days=within_days)
        else:
            rows = activation_check.read_stamped(args.store or service.default_store())
            activated = activated_at(rows, args.merge, activation_check.git_contains(Path.cwd()))
            code, record = observe_merged(
                args.repo, base=args.base, merge=args.merge, platform_repo=args.platform_repo, proven=proven,
                activated=activated, pages=forge_api.api_pages, verdict=forge.verdict, compare=forge.compare,
                pinned=forge.pinned)
    except (sqlite3.Error, OSError) as error:
        print(f"lock-bump: the activation record cannot be read: {error}", file=sys.stderr)
        return 2
    except forge_api.ForgeError as error:
        print(f"lock-bump: {error}", file=sys.stderr)
        return 2
    print(json.dumps(record, sort_keys=True, separators=(",", ":")))
    return code


if __name__ == "__main__":
    sys.exit(main())
