"""How long the `.NET Solution` CI job takes on the integration branch, and the one issue filed when it is too slow.

The command `job-time` reads the job's wall time from the run history of `ci.yaml`:

    job-time file --repo <owner>/<name> --branch <branch>
    job-time observed --repo <owner>/<name> --branch <branch> --merge <sha> --runs <n>

CI runs it from source (`python -m agent_tools.delivery.job_time`); it has no row in
the command table of the platform package.

A green run is a completed push run of `WORKFLOW` whose own conclusion is `success` and
whose latest-attempt `JOB` job is completed and green, its wall time being the job's
`started_at` to `completed_at` in milliseconds. The run's conclusion counts as well as the
job's: the CI jobs are independent, so a green job can sit in a red run. A red run is
skipped without reading its jobs.

`file` lists the completed push runs on the branch, newest first by `(created_at, id)`, at
most `SCAN` of them, and takes the wall times of the `RUNS` newest green runs. With fewer
than `RUNS` nothing is filed (`too_few`). A median under `BUDGET_MS` files nothing
(`within`). Otherwise an open issue carrying `MARKER` as a whole line files nothing (`open`,
the lowest number), a filer that would not be trusted raises `Refusal`, and else one issue
is filed (`filed`). Stdout is one line:

    {"action": "filed", "issue": 101, "job": ".NET Solution", "runs": 10, "median_seconds": 250.0}

The issue it files says, in its title and its first sentence, that the median wall time of
the `JOB` job over the last `RUNS` green push runs of `WORKFLOW` on the branch is not under
the `BUDGET_MS` budget. Its body asks for the job to be made faster (its Nix store cache,
its build or its tests) and says that a slow run never fails a change. Its one acceptance
criterion is met when the log of the `OWN_JOB` job on the branch prints `"action": "within"`.
The body starts with `MARKER`; at most one such issue is open, and the marker identifies it
only when a trusted author wrote it.

`observed` takes the runs after the merge run, the earliest push run whose head is `--merge`,
which is an exclusive boundary: it is the first run that can save the new cache, so the
window counts the runs that follow it. It walks them oldest first, stops at a run that has
not completed, skips a red run, and takes `--runs` green ones. Fewer is `not_yet`, else the
median under `BUDGET_MS` is `met` and anything else `not_met`. It prints
`{"state", "job", "runs", "median_seconds", "budget_seconds"}` and exits 0 met, 1 not met,
`NOT_YET_EXIT` not yet.

Both subcommands exit 2 with `job-time: <reason>` on stderr and nothing on stdout for a
`Refusal`, a `ForgeError`, a `--repo` outside `<owner>/<name>`, a `--merge` that is not 40
lowercase hex digits or a `--runs` below 1. A payload it cannot trust is a `ForgeError` too: a
run with no `conclusion` key (an explicit null is read) and a green job whose times cannot be
read or end before they start, since dropping such a job would let a later run take its place.
The workflow token needs `actions: read` for the
run and job reads, and `issues: write` to file.
"""

import argparse
import json
import re
import statistics
import sys
from collections.abc import Iterable, Sequence
from datetime import datetime, timezone
from typing import NamedTuple, Protocol
from urllib.parse import quote

from agent_tools.delivery import cleanup_issue
from agent_tools.delivery.cleanup_issue import Issue, Refusal
from agent_tools.system import forge_api

COMMAND = "job-time"
WORKFLOW = "ci.yaml"
JOB = ".NET Solution"
RUNS = 10
SCAN = 50
BUDGET_MS = 240_000
MARKER = "<!-- agent:job-time v1 -->"
OWN_JOB = "Job Time"
NOT_YET_EXIT = 75
SHA = re.compile(r"[0-9a-f]{40}")
TIME_FORMAT = "%Y-%m-%dT%H:%M:%SZ"


def instant(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        return datetime.strptime(value, TIME_FORMAT).replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def wall_ms(job: dict) -> int | None:
    """The wall time of a green `JOB` job in milliseconds, `None` for any other job.

    A green job whose times cannot be read, or end before they start, is a payload error:
    dropping it would let the next green run take its place in the window.
    """
    if job.get("name") != JOB or job.get("status") != "completed" \
            or job.get("conclusion") != "success":
        return None
    started, ended = instant(job.get("started_at")), instant(job.get("completed_at"))
    if started is None or ended is None:
        raise invalid("a green job has an unreadable started_at or completed_at")
    if ended < started:
        raise invalid("a green job completed before it started")
    return int(round((ended - started).total_seconds() * 1000))


class Reading(NamedTuple):
    runs: int
    median_ms: float | None


def reading(samples: Sequence[int]) -> Reading:
    use = samples[:RUNS]
    if len(use) < RUNS:
        return Reading(len(use), None)
    return Reading(len(use), statistics.median(use))


def is_job_time(body: str) -> bool:
    return any(line.rstrip(" \r\t") == MARKER for line in body.splitlines())


def open_job_time(issues: Iterable[Issue]) -> list[int]:
    return sorted(issue.number for issue in issues if is_job_time(issue.body))


def draft(found: Reading, branch: str) -> tuple[str, str]:
    median = f"{found.median_ms / 1000:.1f}"
    budget = BUDGET_MS // 1000
    title = (f"Job time: the {JOB} job's median wall time over the last {RUNS} green runs "
             f"is {median} s, not under the {budget} s budget")
    body = (
        f"{MARKER}\n"
        f"The median wall time of the {JOB} job over the last {RUNS} green push runs of "
        f"{WORKFLOW} on {branch} is {median} s, not under the {budget} s budget.\n"
        "\n## What to change\n\n"
        f"Make the {JOB} job faster (its Nix store cache, its build or its tests) until the "
        f"median of its last {RUNS} green runs is under {budget} s. A slow run never fails a "
        "change; this issue is the only signal.\n"
        "\n## Acceptance criteria\n\n"
        f"- [ ] [evidence] The median wall time of the {JOB} job over the last {RUNS} green "
        f"push runs on {branch} is under {budget} s — measured: the {OWN_JOB} job log on "
        f'{branch} prints "action": "within"\n')
    return title, body


class Outcome(NamedTuple):
    action: str
    issue: int | None
    reading: Reading


class Tracker(Protocol):
    def open_issues(self) -> list[Issue]: ...

    def trusted_writer(self) -> bool: ...

    def create(self, title: str, body: str) -> int: ...


def run(tracker: Tracker, samples: Sequence[int], branch: str) -> Outcome:
    found = reading(samples)
    if found.median_ms is None:
        return Outcome("too_few", None, found)
    if found.median_ms < BUDGET_MS:
        return Outcome("within", None, found)
    numbers = open_job_time(tracker.open_issues())
    if numbers:
        return Outcome("open", numbers[0], found)
    if not tracker.trusted_writer():
        raise Refusal("the filer is not a trusted author: its issue would be invisible to the next run")
    return Outcome("filed", tracker.create(*draft(found, branch)), found)


def rounded(ms: float) -> float:
    return round(ms / 1000, 3)


def output(outcome: Outcome) -> str:
    found = outcome.reading
    return json.dumps({
        "action": outcome.action,
        "issue": outcome.issue,
        "job": JOB,
        "runs": found.runs,
        "median_seconds": None if found.median_ms is None else rounded(found.median_ms),
    })


def invalid(detail: str) -> forge_api.ForgeError:
    return forge_api.ForgeError("payload_invalid", detail)


def listed(listing: object, with_sha: bool = False) -> list[dict]:
    found = listing.get("workflow_runs") if isinstance(listing, dict) else None
    if not isinstance(found, list) or not all(
            isinstance(item, dict) and isinstance(item.get("id"), int)
            and not isinstance(item.get("id"), bool) and isinstance(item.get("created_at"), str)
            and "conclusion" in item
            and (item["conclusion"] is None or isinstance(item["conclusion"], str))
            and (not with_sha or isinstance(item.get("head_sha"), str))
            for item in found):
        raise invalid("the run listing is not a list of runs with an id, a created_at and a conclusion")
    return found


def order(found: list[dict]) -> list[dict]:
    return sorted(found, key=lambda item: (item["created_at"], item["id"]))


class GitHubJobTime(cleanup_issue.GitHubTracker):
    def listing(self) -> str:
        branch = quote(self.branch or "", safe="")
        return f"repos/{self.slug}/actions/workflows/{WORKFLOW}/runs?branch={branch}&event=push"

    def wall_of(self, run_id: int) -> int | None:
        """The wall time of the run's `JOB` job of the latest attempt, `None` when it is not green."""
        listing = forge_api.api_get(
            f"repos/{self.slug}/actions/runs/{run_id}/jobs?filter=latest&per_page=100")
        jobs = listing.get("jobs") if isinstance(listing, dict) else None
        if not isinstance(jobs, list):
            raise invalid(f"run {run_id}: the jobs are not a list")
        job = next((item for item in jobs if isinstance(item, dict) and item.get("name") == JOB), None)
        return None if job is None else wall_ms(job)

    def samples(self) -> list[int]:
        found: list[int] = []
        runs = listed(forge_api.api_get(f"{self.listing()}&status=completed&per_page={SCAN}"))
        for item in reversed(order(runs)):
            if item["conclusion"] != "success":
                continue
            wall = self.wall_of(item["id"])
            if wall is not None:
                found.append(wall)
            if len(found) == RUNS:
                break
        return found

    def window(self, merge: str, runs: int) -> tuple[str, list[dict]]:
        """(state, rows) of the first `runs` green runs after the merge run."""
        at_merge = [item for item in listed(
            forge_api.api_get(f"{self.listing()}&head_sha={merge}&per_page=100"), True)
            if item["head_sha"] == merge]
        if not at_merge:
            return "not_yet", []
        first = min(at_merge, key=lambda item: (item["created_at"], item["id"]))
        pages = forge_api.api_pages(f"{self.listing()}&created=>={first['created_at']}&per_page=100")
        found = {item["id"]: item for page in pages for item in listed(page, True)}
        rows: list[dict] = []
        for item in order(list(found.values())):
            if (item["created_at"], item["id"]) <= (first["created_at"], first["id"]):
                continue
            if item.get("status") != "completed":
                break
            if item["conclusion"] != "success":
                continue
            wall = self.wall_of(item["id"])
            if wall is not None:
                rows.append({"run": item["id"], "head_sha": item["head_sha"], "wall_seconds": wall / 1000})
            if len(rows) == runs:
                break
        if len(rows) < runs:
            return "not_yet", rows
        median = statistics.median(row["wall_seconds"] for row in rows) * 1000
        return ("met" if median < BUDGET_MS else "not_met"), rows


def report(state: str, rows: list[dict]) -> tuple[int, str]:
    median = statistics.median(row["wall_seconds"] for row in rows) if state != "not_yet" else None
    line = json.dumps({"state": state, "job": JOB, "runs": rows, "median_seconds": median,
                       "budget_seconds": BUDGET_MS / 1000})
    return {"met": 0, "not_met": 1, "not_yet": NOT_YET_EXIT}[state], line


def parser() -> argparse.ArgumentParser:
    top = argparse.ArgumentParser(prog=COMMAND)
    commands = top.add_subparsers(dest="command", required=True)
    for name in ("file", "observed"):
        sub = commands.add_parser(name)
        sub.add_argument("--repo", required=True)
        sub.add_argument("--branch", required=True)
        if name == "observed":
            sub.add_argument("--merge", required=True)
            sub.add_argument("--runs", required=True)
    return top


def window_size(args: argparse.Namespace) -> int:
    if not SHA.fullmatch(args.merge):
        raise Refusal(f"--merge is not 40 lowercase hex digits: {args.merge}")
    try:
        runs = int(args.runs)
    except ValueError:
        raise Refusal(f"--runs is not an integer: {args.runs}") from None
    if runs < 1:
        raise Refusal(f"--runs is below 1: {args.runs}")
    return runs


def execute(args: argparse.Namespace) -> tuple[int, str]:
    if not cleanup_issue.SLUG.fullmatch(args.repo):
        raise Refusal(f"--repo is not <owner>/<name>: {args.repo}")
    if args.command == "file":
        tracker = GitHubJobTime(args.repo, args.branch)
        return 0, output(run(tracker, tracker.samples(), args.branch))
    runs = window_size(args)
    return report(*GitHubJobTime(args.repo, args.branch).window(args.merge, runs))


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        code, line = execute(args)
    except (Refusal, forge_api.ForgeError) as error:
        print(f"{COMMAND}: {error}", file=sys.stderr)
        return 2
    print(line)
    return code


if __name__ == "__main__":
    sys.exit(main())
