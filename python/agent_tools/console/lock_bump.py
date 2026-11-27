"""`lock_bump`: one pass that offers a proven revision to one project as a lock bump pull request.

The record `~/.agents/state/console/lock-bumps.json` is `{"format": 1, "projects": {<project>: {"revision",
"pull", "outcome": "open"|"merged"|"red"|"closed", "issue", "from"}}}` for the last bump of each project; an
absent file is empty and an unreadable or malformed one is `BumpRefused`, never reset. Open bumps are read
from the forge each pass. The pass takes only the registry entry whose `project_id` is `project`. Order:
every open bump of another revision is closed (`replaced`); an open bump of `latest` is settled by its
required checks (`merged` on green, `filed` once and then `red_known` on red, `pending`); a revision whose
record is not open is `done` and never opened again, so the next proven revision is the retry; otherwise
a lock that is behind `latest` gets one built branch and one pull request (`opened`). The record is written
after each forge write. A red bump is never merged or closed by the pass before a newer revision arrives.

`Bumper` is the console's pass: it reads the registry and the latest proven revision, runs `bump_pass` and
prints one `console: lock_bump <project> <action> <revision> <pull> <issue>` line per step, or one
`console: lock_bump_failed` line when the pass is refused. `start` runs it in a daemon thread every ten
minutes until its stop event is set, and that event is the pass's `cancel`.

`python -m agent_tools.console.lock_bump observed --repo O/N` is the evidence check: it finds the latest merged
`lock-bump-<revision>` pull request of the repository and judges its required contexts as the merge does.
It prints one JSON line and exits 0 met, 1 not met, 75 when no bump has merged, 2 on a forge error.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tempfile
import threading
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import NamedTuple, Protocol, TextIO

from agent_tools.console import approve
from agent_tools.console import lock_bump_forge
from agent_tools.console.lock_bump_forge import Checks, GitHubBumpForge, OpenBump
from agent_tools.console.lock_bump_tree import BRANCH, BumpRefused, GitBuilder, branch_for
from agent_tools.delivery import proof_run
from agent_tools.project_contract import agent_platform
from agent_tools.system import forge_api

FORMAT = 1
LOCK_BUMP_SECONDS = 600.0
LOCK_BUMP_THREAD = "console-lock-bump"
MARKER = "<!-- agent:lock-bump v1 -->"
RED_MARKER = "<!-- agent:lock-bump-red v1 -->"
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


class Builder(Protocol):
    def pin(self, root: Path, slug: str, base: str, cancel: threading.Event | None = None) -> str: ...

    def build(self, root: Path, slug: str, base: str, revision: str,
              cancel: threading.Event | None = None) -> str: ...


def default_state_path() -> Path:
    return agent_platform.state_root() / "console" / "lock-bumps.json"


def _number(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _valid_record(record: object) -> bool:
    return (isinstance(record, dict) and set(record) == {"revision", "pull", "outcome", "issue", "from"}
            and isinstance(record["revision"], str) and REVISION.fullmatch(record["revision"]) is not None
            and _number(record["pull"]) and record["pull"] > 0 and record["outcome"] in OUTCOMES
            and (record["issue"] is None or _number(record["issue"]))
            and (record["from"] is None or (isinstance(record["from"], str)
                                            and REVISION.fullmatch(record["from"]) is not None)))


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
    if (state.get("format") != FORMAT or not isinstance(projects, dict) or set(state) != {"format", "projects"}
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


def _issue_text(project: str, latest: str, pull: int, failing: Sequence[str]) -> tuple[str, str]:
    checks = ", ".join(failing)
    body = (f"The lock bump of {project} to {latest} fails: {checks}.\n\n"
            f"Pull request: https://github.com/{project}/pull/{pull}\n\n"
            + "\n".join(f"- {name}" for name in failing)
            + "\n\nOnly the lock changed, so the failure is the platform's. The project stays on its old "
              "lock until the next proven revision is offered.\n\n" + RED_MARKER)
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
            save({"revision": latest, "pull": number, "outcome": "open", "issue": None, "from": None})
        return steps + [_settle(project, latest, number, record, forge, tracker, save, cancel)]
    if record is not None and record["revision"] == latest:
        number = record["pull"]
        if record["outcome"] != "open":
            return steps + [step("done", number, record["issue"])]
        ended = forge.checks(project, number, cancel)
        if ended.state in ("merged", "closed"):
            save({**record, "outcome": ended.state})
            return steps + [step("ended", number, record["issue"], ended.state)]
        return steps + [step("pending", number)]
    root = Path(matching[0]["root"])
    pin = builder.pin(root, project, base, cancel=cancel)
    if pin == latest:
        return steps + [step("current")]
    status = forge.compare(platform_repo, pin, latest, cancel)
    if status != "ahead":
        return steps + [step("not_behind", detail=status)]
    branch = builder.build(root, project, base, latest, cancel=cancel)
    title, body = _pull_text(platform_repo, latest, pin)
    number = forge.open_pull(project, branch, base, title, body, cancel)
    save({"revision": latest, "pull": number, "outcome": "open", "issue": None, "from": pin})
    return steps + [step("opened", number)]


def _settle(project, latest, number, record, forge, tracker, save, cancel) -> Step:
    checks = forge.checks(project, number, cancel)
    if checks.state == "green":
        forge.merge(project, number, checks.head, cancel)
        save({**record, "outcome": "merged"})
        return Step(project, "merged", latest, number, record["issue"], None)
    if checks.state == "red":
        if record["issue"] is not None:
            return Step(project, "red_known", latest, number, record["issue"], None)
        issue = tracker.create(*_issue_text(project, latest, number, checks.failing))
        save({**record, "outcome": "red", "issue": issue})
        return Step(project, "filed", latest, number, issue, None)
    if checks.state in ("merged", "closed"):
        save({**record, "outcome": checks.state})
        return Step(project, "ended", latest, number, record["issue"], checks.state)
    return Step(project, "pending", latest, number, record["issue"], None)


class PlatformTracker:
    def __init__(self, platform_repo: str):
        self._platform_repo = platform_repo

    def create(self, title: str, body: str) -> int:
        return forge_api.create_issue(self._platform_repo, title, body)


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


def observe(repo: str, *, pages: Callable[[str], list], verdict: Callable[[str, int], Checks]) -> tuple[int, dict]:
    """The exit code and the printed record of the latest merged bump of `repo`, judged on required contexts."""
    merged = []
    for page in pages(f"repos/{repo}/pulls?state=closed&per_page=100"):
        for pull in page if isinstance(page, list) else []:
            head = pull.get("head") if isinstance(pull, dict) else None
            head = head if isinstance(head, dict) else {}
            source = head.get("repo") if isinstance(head.get("repo"), dict) else {}
            ref, sha, number = head.get("ref"), head.get("sha"), pull.get("number")
            if (isinstance(pull.get("merged_at"), str) and isinstance(ref, str) and BRANCH.fullmatch(ref)
                    and source.get("full_name") == repo and isinstance(sha, str) and approve.COMMIT.fullmatch(sha)
                    and isinstance(number, int) and not isinstance(number, bool)):
                merged.append((pull["merged_at"], number))
    if not merged:
        return 75, {"pull": None, "state": "not_yet"}
    number = max(merged)[1]
    if verdict(repo, number).state == "green":
        return 0, {"pull": number, "state": "met"}
    return 1, {"pull": number, "state": "not_met"}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="lock_bump", description="Check that a lock bump merged green.")
    modes = parser.add_subparsers(dest="mode", required=True)
    modes.add_parser("observed").add_argument("--repo", required=True, metavar="O/N")
    args = parser.parse_args(argv)
    if re.fullmatch(r"[A-Za-z0-9._-]+/[A-Za-z0-9._-]+", args.repo) is None:
        parser.error("--repo is owner/name")
    try:
        code, record = observe(args.repo, pages=forge_api.api_pages, verdict=lock_bump_forge.GitHubBumpForge().verdict)
    except forge_api.ForgeError as error:
        print(f"lock-bump: {error}", file=sys.stderr)
        return 2
    print(json.dumps(record, sort_keys=True, separators=(",", ":")))
    return code


if __name__ == "__main__":
    sys.exit(main())
