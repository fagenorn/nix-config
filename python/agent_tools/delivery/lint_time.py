"""The lint stopwatch: how long each never-rise lint takes on both sides of the comparison.

A lint is a never-rise enforcer (`agent_tools.delivery.never_rise.Enforcer`), run
once on the merge base and once on the branch. `Stopwatch.timed` wraps each
enforcer's `find` so its elapsed time is kept under the enforcer's rule. The
comparison reads the base side first, so the first `find` call of a rule is its
base time and every later call adds to its branch time. A `find` that raises is
timed too, and its exception propagates unchanged.

Each side is `int(round(seconds * 1000))` milliseconds, and a lint's `ms` is the
sum of its two sides. `record()` answers `None` when no wrapped `find` ran.

The record is one line, `RECORD_PREFIX` and a compact JSON object with sorted keys:

    lint-times v1 {"lints":[{"base_ms":2000,"branch_ms":3000,"lint":"A"}],"total_ms":5000}

`total_ms` is the sum of every lint's two sides. `conformance run --lint-times`
prints that line on stderr. `parse_log` reads one back from a job log: it takes
the one line that starts with the prefix after an optional leading BOM and an
optional GitHub timestamp, answers `None` for none and raises `ValueError` for
two, or for a payload that is not an object with exactly `lints` and `total_ms`,
whose `lints` is a non-empty list of objects with exactly `base_ms`, `branch_ms`
and `lint`, each `lint` a distinct non-empty string, each `*_ms` a non-negative
`int` that is not a `bool`, and whose `total_ms` is their exact sum.

The command `lint-time` reads those records back from the Conformance job logs:

    lint-time file --repo <owner>/<name> --branch <branch>
    lint-time observed --repo <owner>/<name> --branch <branch>

`file` lists the completed push runs of `conformance.yaml` on the branch, newest
first by `(created_at, id)`, at most `SCAN` of them. For each run it takes the
`Conformance` job of the latest attempt and reads that job's log. A run with no such
job, a log the forge no longer holds (404 or 410) or no record line is skipped, and
reading stops at the `RUNS` newest records. A malformed record is an error.

With fewer than `RUNS` records nothing is filed (`too_few`). Otherwise a lint's
median is taken over the records that carry it, and the total's median over every
record. A total median at or below `BUDGET_MS` files nothing (`within`). Over it,
an open issue carrying `MARKER` as a whole line, written by a trusted author, files
nothing (`open`, the lowest number). Otherwise one issue is filed (`filed`) whose
title and body name the lint with the highest median, ties going to the lint id
that sorts first. A filer that would not be trusted raises `Refusal` and files
nothing. Stdout is one line:

    {"action": "filed", "issue": 101, "runs": 20, "median_seconds": 65.0,
     "slowest": {"lint": "B17", "median_seconds": 40.0}}

`observed` reads the newest completed push run of `lint-time.yaml` on the branch,
its `Lint Time` job log, and the last line that is a JSON object with an `action`.
It prints `{"state": ..., "run": ..., "median_seconds": ..., "slowest": ...}` and
exits 0 (`met`: the action is `within`, `open` or `filed`, with a numeric median
and a named slowest lint), 75 (`not_yet`: no completed run, or `too_few`) or 1
(`not_met`: anything else, a missing output line included).

`file` and `observed` exit 2 with `lint-time: <reason>` on stderr and nothing on
stdout for a `Refusal`, a `ForgeError` or a `--repo` that is not `<owner>/<name>`.
The workflow token needs `actions: read` for the run, job and log reads, and
`issues: write` to file.
"""

import argparse
import dataclasses
import json
import re
import statistics
import sys
import time
from collections.abc import Callable, Iterable, Sequence
from typing import NamedTuple, Protocol
from urllib.parse import quote

from agent_tools.delivery import cleanup_issue
from agent_tools.delivery.cleanup_issue import Issue, Refusal
from agent_tools.delivery.never_rise import Enforcer, Snapshot, Violation
from agent_tools.system import forge_api

COMMAND = "lint-time"
MARKER = "<!-- agent:lint-time v1 -->"
RUNS = 20
BUDGET_MS = 60_000
SCAN = 50
WORKFLOW = "conformance.yaml"
JOB = "Conformance"
OWN_WORKFLOW = "lint-time.yaml"
OWN_JOB = "Lint Time"
RECORD_PREFIX = "lint-times v1 "
LOG_STAMP = re.compile(r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(\.\d+)?Z ")
BOM = "\ufeff"


class LintTime(NamedTuple):
    lint: str
    base_ms: int
    branch_ms: int

    @property
    def ms(self) -> int:
        return self.base_ms + self.branch_ms


class Record(NamedTuple):
    lints: tuple[LintTime, ...]

    @property
    def total_ms(self) -> int:
        return sum(lint.ms for lint in self.lints)


def milliseconds(seconds: float) -> int:
    return int(round(seconds * 1000))


class Stopwatch:
    def __init__(self, clock: Callable[[], float] = time.perf_counter) -> None:
        self._clock = clock
        self._calls: dict[str, list[float]] = {}

    def timed(self, enforcers: Sequence[Enforcer]) -> tuple[Enforcer, ...]:
        """Each enforcer with a `find` that keeps its elapsed time under its rule."""
        return tuple(dataclasses.replace(e, find=self._wrap(e)) for e in enforcers)

    def _wrap(self, enforcer: Enforcer) -> Callable[[Snapshot], list[Violation]]:
        def find(snapshot: Snapshot) -> list[Violation]:
            start = self._clock()
            try:
                return enforcer.find(snapshot)
            finally:
                self._calls.setdefault(enforcer.rule, []).append(self._clock() - start)

        return find

    def record(self) -> Record | None:
        """The lints in the order they first ran, or `None` when none ran."""
        if not self._calls:
            return None
        return Record(tuple(
            LintTime(rule, milliseconds(calls[0]), sum(milliseconds(c) for c in calls[1:]))
            for rule, calls in self._calls.items()))


def record_line(record: Record) -> str:
    payload = {
        "lints": [
            {"base_ms": lint.base_ms, "branch_ms": lint.branch_ms, "lint": lint.lint}
            for lint in record.lints],
        "total_ms": record.total_ms,
    }
    return RECORD_PREFIX + json.dumps(payload, sort_keys=True, separators=(",", ":"))


def milliseconds_of(value: object, name: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ValueError(f"{name} is not a non-negative integer")
    return value


def lint_time_of(entry: object) -> LintTime:
    if not isinstance(entry, dict) or set(entry) != {"base_ms", "branch_ms", "lint"}:
        raise ValueError("a lint is not an object of base_ms, branch_ms and lint")
    lint = entry["lint"]
    if not isinstance(lint, str) or not lint:
        raise ValueError("a lint name is not a non-empty string")
    return LintTime(
        lint, milliseconds_of(entry["base_ms"], "base_ms"),
        milliseconds_of(entry["branch_ms"], "branch_ms"))


def parse_payload(text: str) -> Record:
    try:
        payload = json.loads(text)
    except ValueError as error:
        raise ValueError(f"the record is not JSON: {error}") from error
    if not isinstance(payload, dict) or set(payload) != {"lints", "total_ms"}:
        raise ValueError("the record is not an object of lints and total_ms")
    entries = payload["lints"]
    if not isinstance(entries, list) or not entries:
        raise ValueError("lints is not a non-empty list")
    lints = tuple(lint_time_of(entry) for entry in entries)
    if len({lint.lint for lint in lints}) != len(lints):
        raise ValueError("a lint is repeated")
    record = Record(lints)
    if milliseconds_of(payload["total_ms"], "total_ms") != record.total_ms:
        raise ValueError("total_ms is not the sum of the lints")
    return record


def parse_log(text: str) -> Record | None:
    """The one record line of a job log, `None` for none, `ValueError` for two or a bad one."""
    payloads = []
    for line in text.removeprefix(BOM).splitlines():
        body = LOG_STAMP.sub("", line, count=1)
        if body.startswith(RECORD_PREFIX):
            payloads.append(body[len(RECORD_PREFIX):])
    if len(payloads) > 1:
        raise ValueError("the log holds more than one lint-times record")
    return parse_payload(payloads[0]) if payloads else None


class Reading(NamedTuple):
    runs: int
    median_ms: float | None
    lints: tuple[tuple[str, float], ...]

    @property
    def slowest(self) -> tuple[str, float] | None:
        return self.lints[0] if self.lints else None


def reading(records: Sequence[Record]) -> Reading:
    use = records[:RUNS]
    if len(use) < RUNS:
        return Reading(len(use), None, ())
    per_lint: dict[str, list[int]] = {}
    for record in use:
        for entry in record.lints:
            per_lint.setdefault(entry.lint, []).append(entry.ms)
    medians = sorted(((lint, statistics.median(values)) for lint, values in per_lint.items()),
                     key=lambda item: (-item[1], item[0]))
    return Reading(len(use), statistics.median(r.total_ms for r in use), tuple(medians))


def is_lint_time(body: str) -> bool:
    return any(line.rstrip(" \r\t") == MARKER for line in body.splitlines())


def open_lint_time(issues: Iterable[Issue]) -> list[int]:
    return sorted(issue.number for issue in issues if is_lint_time(issue.body))


def seconds(ms: float) -> str:
    return f"{ms / 1000:.1f}"


def draft(found: Reading, branch: str) -> tuple[str, str]:
    lint, lint_ms = found.slowest
    median = seconds(found.median_ms)
    title = (f"Lint time: median {median} s of the last {RUNS} runs is over the "
             f"{BUDGET_MS // 1000} s budget; slowest lint {lint}")
    rows = "".join(f"| {name} | {seconds(ms)} |\n" for name, ms in found.lints)
    body = (
        f"{MARKER}\n"
        f"The median total lint time of the last {RUNS} completed Conformance runs on {branch} "
        f"is {median} s, over the {BUDGET_MS // 1000} s budget. The slowest lint is {lint}, "
        f"with a median of {seconds(lint_ms)} s.\n"
        "\n## Lints\n\n| Lint | Median seconds |\n|---|---:|\n"
        f"{rows}"
        "\n## What to change\n\n"
        f"Make the slowest lint faster, or the lints together, until the median total is at "
        f"most {BUDGET_MS // 1000} s. A slow run never fails a change; this issue is the only "
        "signal.\n"
        "\n## Acceptance criteria\n\n"
        f"- [ ] [evidence] The median total lint time of the last {RUNS} completed Conformance "
        f"runs on {branch} is at most {BUDGET_MS // 1000} s \u2014 measured: the {OWN_JOB} job "
        f'log on {branch} prints "action": "within"\n')
    return title, body


class Outcome(NamedTuple):
    action: str
    issue: int | None
    reading: Reading


class Tracker(Protocol):
    def open_issues(self) -> list[Issue]: ...

    def trusted_writer(self) -> bool: ...

    def create(self, title: str, body: str) -> int: ...


def run(tracker: Tracker, records: Sequence[Record], branch: str) -> Outcome:
    found = reading(records)
    if found.median_ms is None:
        return Outcome("too_few", None, found)
    if found.median_ms <= BUDGET_MS:
        return Outcome("within", None, found)
    numbers = open_lint_time(tracker.open_issues())
    if numbers:
        return Outcome("open", numbers[0], found)
    if not tracker.trusted_writer():
        raise Refusal("the filer is not a trusted author: its issue would be invisible to the next run")
    title, body = draft(found, branch)
    return Outcome("filed", tracker.create(title, body), found)


def rounded(ms: float) -> float:
    return round(ms / 1000, 3)


def output(outcome: Outcome) -> str:
    found = outcome.reading
    slowest = found.slowest
    return json.dumps({
        "action": outcome.action,
        "issue": outcome.issue,
        "runs": found.runs,
        "median_seconds": None if found.median_ms is None else rounded(found.median_ms),
        "slowest": None if slowest is None else {"lint": slowest[0], "median_seconds": rounded(slowest[1])},
    })


def invalid(detail: str) -> forge_api.ForgeError:
    return forge_api.ForgeError("payload_invalid", detail)


class GitHubLintTime(cleanup_issue.GitHubTracker):
    def runs_of(self, workflow: str, per_page: int) -> list[dict]:
        branch = quote(self.branch or "", safe="")
        listing = forge_api.api_get(
            f"repos/{self.slug}/actions/workflows/{workflow}/runs"
            f"?branch={branch}&event=push&status=completed&per_page={per_page}")
        found = listing.get("workflow_runs") if isinstance(listing, dict) else None
        if not isinstance(found, list) or not all(
                isinstance(item, dict) and isinstance(item.get("id"), int)
                and not isinstance(item.get("id"), bool) and isinstance(item.get("created_at"), str)
                for item in found):
            raise invalid("the run listing is not a list of runs with an id and a created_at")
        return sorted(found, key=lambda item: (item["created_at"], item["id"]), reverse=True)

    def log_of(self, run_id: int, name: str) -> str | None:
        """The log of the run's job called `name`, or `None` when there is none or it is gone."""
        listing = forge_api.api_get(
            f"repos/{self.slug}/actions/runs/{run_id}/jobs?filter=latest&per_page=100")
        jobs = listing.get("jobs") if isinstance(listing, dict) else None
        if not isinstance(jobs, list):
            raise invalid(f"run {run_id}: the jobs are not a list")
        job = next((item for item in jobs if isinstance(item, dict) and item.get("name") == name), None)
        if job is None:
            return None
        job_id = job.get("id")
        if not isinstance(job_id, int) or isinstance(job_id, bool):
            raise invalid(f"run {run_id}: job {name} has no id")
        status, text = forge_api.run_gh(
            ["api", f"repos/{self.slug}/actions/jobs/{job_id}/logs"], allow=(404, 410))
        return None if status else text

    def records(self) -> list[Record]:
        found: list[Record] = []
        for item in self.runs_of(WORKFLOW, SCAN):
            text = self.log_of(item["id"], JOB)
            if text is None:
                continue
            try:
                record = parse_log(text)
            except ValueError as error:
                raise invalid(f"run {item['id']}: {error}") from error
            if record is not None:
                found.append(record)
            if len(found) == RUNS:
                break
        return found

    def latest_output(self) -> tuple[int | None, dict | None]:
        runs = self.runs_of(OWN_WORKFLOW, 1)
        if not runs:
            return None, None
        run_id = runs[0]["id"]
        text = self.log_of(run_id, OWN_JOB)
        payload = None
        for line in (text or "").removeprefix(BOM).splitlines():
            try:
                decoded = json.loads(LOG_STAMP.sub("", line, count=1))
            except ValueError:
                continue
            if isinstance(decoded, dict) and "action" in decoded:
                payload = decoded
        return run_id, payload


def number(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def observed(run_id: int | None, payload: dict | None) -> tuple[int, dict]:
    if run_id is None:
        return 75, {"state": "not_yet", "run": None, "median_seconds": None, "slowest": None}
    action = payload.get("action") if payload else None
    median = payload.get("median_seconds") if payload else None
    slowest = payload.get("slowest") if payload else None
    lint = slowest.get("lint") if isinstance(slowest, dict) else None
    named = lint if isinstance(lint, str) and lint else None
    seen = {"run": run_id, "median_seconds": median if number(median) else None, "slowest": named}
    if action == "too_few":
        return 75, {"state": "not_yet", **seen}
    if action in ("within", "open", "filed") and number(median) and named:
        return 0, {"state": "met", **seen}
    return 1, {"state": "not_met", **seen}


def parser() -> argparse.ArgumentParser:
    top = argparse.ArgumentParser(prog=COMMAND)
    commands = top.add_subparsers(dest="command", required=True)
    for name in ("file", "observed"):
        sub = commands.add_parser(name)
        sub.add_argument("--repo", required=True)
        sub.add_argument("--branch", required=True)
    return top


def execute(args: argparse.Namespace) -> tuple[int, str]:
    if not cleanup_issue.SLUG.fullmatch(args.repo):
        raise Refusal(f"--repo is not <owner>/<name>: {args.repo}")
    tracker = GitHubLintTime(args.repo, args.branch)
    if args.command == "file":
        return 0, output(run(tracker, tracker.records(), args.branch))
    code, state = observed(*tracker.latest_output())
    return code, json.dumps(state)


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
