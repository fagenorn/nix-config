"""Compare a suite timing report with the base branch's and say when the suite grew (issue 1385).

Usage: `python -m agent_tools.delivery.suite_timing compare --head <path> --base <path>
--base-label <label> [--threshold <seconds>]`, or `python -m agent_tools.delivery.suite_timing
join --workflow <path> --shard-job <job> --shards-dir <dir> --out <path> --needs-result
<result>`, or `python -m agent_tools.delivery.suite_timing observed --repo <slug>
--branch <branch> --merge <sha> --runs <n> --before-seconds <b> --target-seconds <t>`

CI runs this module from source (it has no command-table row, after
`agent_tools.delivery.suite_runner`); decision: ADR-delivery-015. It reads two timing
reports, the head's and the base's, as the suite runner writes them, and prints a
line for the pull request's job summary, an empty line and a table of the head's
slowest tests.

Reports. Each is strict JSON (no duplicate key, no NaN or infinity) whose top level is
an object with `version` the integer 1, `member_seconds` a finite number of at least 0,
and `timings` a non-empty list of objects, each with a non-empty string `member` and a
finite `seconds` of at least 0. Booleans are not numbers. The rows must be slowest first
(a row's `seconds` is not above the row before it) and name each member once; the runner
writes both properties, so only a report it did not write is refused. Other keys are
ignored.

Growth. The runner speed factor is the median (not the mean) of `head_s / base_s` over
the members in both reports whose base time is at least 1.0 s, or 1.0 when there is
none. Growth is the head's `member_seconds` minus the factor times the base's, so a
uniformly slower runner is not growth and a removed member lowers it. The largest growth
is the head member with the greatest `seconds - factor * base_seconds`, the first in head
order on a tie, a member absent from the base counting as 0 s there. The comparison with
the threshold is made on the unrounded growth and is strict: growth equal to the
threshold is within it. The arithmetic is decimal on the numbers as the report writes
them, so a float's error does not move growth across the threshold. Rounding is for
display only.

Output, on stdout, one of three lines (`{t}` is the threshold in `%g` form):

- grew: `Suite time grew by <g>s over <label>, past the <t>s threshold: <base>s to <head>s
  of member time at runner speed <factor>. Largest growth: <member> (+<delta>s). Slowest
  test: <member> (<s>s).`
- within: `Suite time changed by <+g>s over <label>, within the <t>s threshold: <base>s to
  <head>s of member time at runner speed <factor>. Slowest test: <member> (<s>s).`
- no baseline: `Suite time: no <label> baseline to compare with; <head>s of member time.
  Slowest test: <member> (<s>s).`

Then an empty line, `| Slowest tests | Seconds |`, `|---|---:|` and one
`| <member> | <seconds> |` row for each of the head's ten slowest tests.

A base that is missing, unreadable or refused by the report checks is no baseline: stderr
gets `suite-timing: base: <reason>` so a corrupt, truncated or newer-version baseline is
named in the job log and does not look like a cache miss, and the no-baseline line is
printed. CI sends only stdout to the job summary.

Exits. 0 whether the suite grew or not, and with no baseline. 2 for a usage error, a
`--threshold` that is not finite and at least 0, or a head report that is refused:
`suite-timing: <reason>` goes to stderr and nothing to stdout.

Join. CI runs the suite as shards, each uploading its runner report as the artifact
`suite-timing-shard-<n>-attempt-<a>-<success|failure>` (`<a>` the run attempt, the last
word the job's status when it uploaded) holding `suite-timing.json`; `join` makes one
report of them, a verdict on each shard and an exit status. Every line goes to stdout,
prefixed `suite-timing: `.

1. The shards expected are `1..N`, N read from the workflow, never from the reports: in
   the job `--shard-job` (its `  <job>:` line once), exactly one line
   `        shard: [1, ..., N]` listing 1 to N. A workflow that is unreadable or declares
   otherwise prints `<workflow path>: <reason>`, writes nothing and exits 1.
2. The artifacts are the subdirectories of `--shards-dir` (a missing one is none). A name
   of another form, two names of one shard and attempt, or a shard above N prints its
   reason, writes nothing and exits 1. For each shard its highest attempt is read, so a
   rerun supersedes the earlier attempt.
3. Each picked artifact's report must be a valid shard report (a runner report with
   `shard` and `shard_count` whose counts agree with its rows) of that shard and of N
   shards. A refused report fails its shard and blocks the joined report; the surviving
   reports do not stand in for it.
4. One line for each shard, in order, the first that applies: `shard i of N failed: it
   wrote no report`; `... failed: its report is invalid: <reason>`; `... failed: <f> of
   <m> members failed: <those members, in row order>`; `... failed: its job had failed
   when it uploaded a passing report`; else `shard i of N passed: <m> members in <w>s`.
5. When every shard has a valid report and no member is in two of them, the joined report
   is written to `--out`; a member in two prints its reason and nothing is written. Its
   keys are `version` 1, `members`, `passed`, `failed` (sums), `jobs` (the largest),
   `shard_count`, `wall_seconds` (the slowest shard's), `member_seconds` (the sum),
   `cpu_seconds` (the sum), `timings` (every row, slowest first, ties by shard then row
   order) and `shard_summaries` (`shard`, `members`, `failed`, `wall_seconds` of each),
   so `compare` reads it as it reads a runner report.
6. The last line is `failed shards: <numbers>` and the exit 1 when any shard failed. Else,
   when `--needs-result` (the shard jobs' conclusion) is not `success`, it is the line
   `the shard jobs concluded <result> though every shard uploaded a passing report from a
   passing job` then `unconfirmed shards: 1, ..., N`, exit 1. Else `every shard passed`,
   exit 0. 2 is a usage error.

Observed. The verify check `home/common/verify-pending/checks/agent-workflow-tests-wall`
reads the required check's wall time on `--branch` after a merge. `--repo` is
`<owner>/<name>` of `[A-Za-z0-9_.-]+`, `--merge` 40 lowercase hex digits, `--runs` an
integer of at least 1, the seconds finite and above 0; else stderr gets
`suite-timing: <reason>`, nothing goes to stdout and the exit is 2. The merge run is the
earliest (by `created_at`, then id) push run of `ci.yaml` whose `head_sha` is the merge,
found by that sha, so a reading taken after any number of newer runs finds it. The window
is that run and the runs after it, paged from its `created_at`, deduplicated by id and
sorted ascending by `(created_at, id)`, the first `--runs` of them; with fewer, or with no
merge run, the state is `not_yet` (exit 75). Each run is read on its first attempt only
(`attempts/1/jobs`), so a rerun changes no sample. Its wall seconds are the completion of
the job named `Agent Workflow Tests` minus the earliest start of the jobs named `Agent
Workflow Tests Shard <n>`; a missing or unfinished job, or an unreadable time, is
`not_yet` while the run's listed status is not `completed` and `not_met` (exit 1, the run
named on stderr) after. The state is `met` (exit 0) when the median of the walls is
strictly below `--target-seconds`, else `not_met`. stdout is one JSON line: `state`,
`runs` (each `run`, `head_sha`, `wall_seconds`, `before_seconds`, `change_seconds` (wall
minus `--before-seconds`), `conclusion` (the final job's, on the first attempt)),
`median_seconds` (null unless every run was measured) and `target_seconds`. A forge
failure or an unreadable listing is exit 2 with `suite-timing: <reason>`.

This module imports only the standard library and `agent_tools` modules that do, because
CI runs it with the runner image's system `python3`.
"""

import argparse
import json
import math
import re
import statistics
import sys
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from urllib.parse import quote

from agent_tools import canonical
from agent_tools.delivery import suite_runner
from agent_tools.system import forge_api

DEFAULT_THRESHOLD = 60.0
FACTOR_FLOOR_SECONDS = 1.0
SLOWEST_ROWS = 10
REPORT_VERSION = 1
SHARD_REPORT = "suite-timing.json"
FINAL_JOB = "Agent Workflow Tests"
SHARD_JOB_PREFIX = "Agent Workflow Tests Shard "
NOT_YET_EXIT = 75
_SLUG_RE = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+")
_SHA_RE = re.compile(r"[0-9a-f]{40}")
SHARD_ARTIFACT_RE = re.compile(
    r"suite-timing-shard-([1-9][0-9]*)-attempt-([1-9][0-9]*)-(success|failure)")
_MATRIX_LINE_RE = re.compile(r"        shard: \[([1-9][0-9]*(?:, [1-9][0-9]*)*)\]")


class ReportError(ValueError):
    """A timing report that cannot be used; the message is the reason."""


@dataclass(frozen=True)
class Comparison:
    base_seconds: float
    head_seconds: float
    factor: float
    growth: float
    largest_member: str
    largest_delta: float


def _is_number(value: object) -> bool:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return False
    try:
        return math.isfinite(value) and value >= 0
    except OverflowError:  # an integer too large to be a float is not a finite number
        return False


def load_report(path: Path) -> dict:
    """Parse and check the report at `path`; raise `ReportError` with the reason."""
    try:
        text = Path(path).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as error:
        raise ReportError(f"cannot read {path}: {error}") from error
    try:
        report = json.loads(text, object_pairs_hook=canonical.reject_duplicate_keys,
                            parse_constant=canonical.reject_nonfinite_literal)
    except (ValueError, RecursionError) as error:
        raise ReportError(f"{path} is not valid JSON: {error}") from error
    if not isinstance(report, dict):
        raise ReportError("the top level is not an object")
    version = report.get("version")
    if isinstance(version, bool) or version != REPORT_VERSION or not isinstance(version, int):
        raise ReportError(f"version is {version!r}, not {REPORT_VERSION}")
    if not _is_number(report.get("member_seconds")):
        raise ReportError("member_seconds is not a finite number of at least 0")
    timings = report.get("timings")
    if not isinstance(timings, list) or not timings:
        raise ReportError("timings is not a non-empty list")
    seen: set[str] = set()
    previous: float | None = None
    for index, row in enumerate(timings):
        if not isinstance(row, dict):
            raise ReportError(f"timings[{index}]: not an object")
        member = row.get("member")
        if not isinstance(member, str) or not member:
            raise ReportError(f"timings[{index}]: member is not a non-empty string")
        seconds = row.get("seconds")
        if not _is_number(seconds):
            raise ReportError(f"timings[{index}]: seconds is not a finite number of at least 0")
        if previous is not None and seconds > previous:
            raise ReportError(f"timings[{index}]: {seconds} s is above the row before it; "
                              "the runner writes them slowest first")
        if member in seen:
            raise ReportError(f"timings[{index}]: member {member} appears twice")
        seen.add(member)
        previous = seconds
    return report


def _seconds_by_member(report: dict) -> dict[str, float]:
    return {row["member"]: row["seconds"] for row in report["timings"]}


def speed_factor(base: dict, head: dict) -> float:
    """The median of head/base over members in both reports whose base time is at least
    `FACTOR_FLOOR_SECONDS`, or 1.0 when there is none."""
    base_seconds = _seconds_by_member(base)
    ratios = [row["seconds"] / base_seconds[row["member"]] for row in head["timings"]
              if base_seconds.get(row["member"], 0.0) >= FACTOR_FLOOR_SECONDS]
    return float(statistics.median(ratios)) if ratios else 1.0


def _exact(value: float) -> Decimal:
    """The decimal a report writes for `value`, so `64.4 - 4.4` is 60.0 and not 60.00000000000001."""
    return Decimal(repr(float(value)))


def compare(base: dict, head: dict) -> Comparison:
    factor = speed_factor(base, head)
    scale = _exact(factor)
    base_seconds = _seconds_by_member(base)
    largest_member = ""
    largest_delta = Decimal("-Infinity")
    for row in head["timings"]:
        delta = _exact(row["seconds"]) - scale * _exact(base_seconds.get(row["member"], 0.0))
        if delta > largest_delta:
            largest_member, largest_delta = row["member"], delta
    return Comparison(
        base_seconds=base["member_seconds"],
        head_seconds=head["member_seconds"],
        factor=factor,
        growth=float(_exact(head["member_seconds"]) - scale * _exact(base["member_seconds"])),
        largest_member=largest_member,
        largest_delta=float(largest_delta),
    )


def _shown(value: float) -> float:
    return round(value, 1) + 0.0


def summary_line(head: dict, comparison: Comparison | None, *, threshold: float,
                 base_label: str) -> str:
    slowest = head["timings"][0]
    tail = f"Slowest test: {slowest['member']} ({slowest['seconds']:.1f}s)."
    if comparison is None:
        return (f"Suite time: no {base_label} baseline to compare with; "
                f"{head['member_seconds']:.1f}s of member time. {tail}")
    figures = (f"{comparison.base_seconds:.1f}s to {comparison.head_seconds:.1f}s of member "
               f"time at runner speed {comparison.factor:.2f}.")
    if comparison.growth > threshold:
        return (f"Suite time grew by {_shown(comparison.growth):.1f}s over {base_label}, "
                f"past the {threshold:g}s threshold: {figures} Largest growth: "
                f"{comparison.largest_member} (+{_shown(comparison.largest_delta):.1f}s). {tail}")
    return (f"Suite time changed by {_shown(comparison.growth):+.1f}s over {base_label}, "
            f"within the {threshold:g}s threshold: {figures} {tail}")


def declared_shard_count(workflow_text: str, job: str) -> int:
    """The N of the one `        shard: [1, ..., N]` line in the block of the job `job`."""
    lines = workflow_text.splitlines()
    heads = [index for index, line in enumerate(lines) if line == f"  {job}:"]
    if len(heads) != 1:
        raise ReportError(f"job {job} is not declared once")
    block: list[str] = []
    for line in lines[heads[0] + 1:]:
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and len(line) - len(line.lstrip(" ")) <= 2:
            break
        block.append(line)
    matches = [match for line in block if (match := _MATRIX_LINE_RE.fullmatch(line))]
    if len(matches) != 1:
        raise ReportError(f"job {job} has no one 'shard: [1, ..., N]' matrix line")
    listed = [int(number) for number in matches[0].group(1).split(", ")]
    if listed != list(range(1, len(listed) + 1)):
        raise ReportError(f"the matrix shards are {listed}, not 1 to {len(listed)}")
    return len(listed)


def load_shard_report(path: Path) -> dict:
    """`load_report` of a shard's report, and its shard and counts checked as the runner
    writes them; raise `ReportError` with the reason."""
    report = load_report(path)
    for key in ("shard", "shard_count", "members", "passed", "failed", "jobs"):
        value = report.get(key)
        if isinstance(value, bool) or not isinstance(value, int):
            raise ReportError(f"{key} is {value!r}, not an integer")
    if not 1 <= report["shard"] <= report["shard_count"]:
        raise ReportError(f"shard {report['shard']} is not within 1 to {report['shard_count']}")
    for key in ("members", "passed", "failed"):
        if report[key] < 0:
            raise ReportError(f"{key} is {report[key]}, below 0")
    if report["jobs"] < 1:
        raise ReportError(f"jobs is {report['jobs']}, below 1")
    for key in ("wall_seconds", "cpu_seconds"):
        if not _is_number(report.get(key)):
            raise ReportError(f"{key} is not a finite number of at least 0")
    for index, row in enumerate(report["timings"]):
        if not isinstance(row.get("passed"), bool):
            raise ReportError(f"timings[{index}]: passed is not a boolean")
    members, failed, rows = report["members"], report["failed"], report["timings"]
    if members != len(rows):
        raise ReportError(f"members is {members} but timings has {len(rows)} rows")
    unpassed = sum(1 for row in rows if not row["passed"])
    if failed != unpassed:
        raise ReportError(f"failed is {failed} but {unpassed} timing rows did not pass")
    if report["passed"] != members - failed:
        raise ReportError(f"passed is {report['passed']}, not members {members} minus "
                          f"failed {failed}")
    return report


def pick_artifacts(names: Iterable[str]) -> dict[int, tuple[int, str, str]]:
    """Each shard's `(attempt, status, name)` of its highest attempt among the artifact
    `names`; raise `ReportError` for a name of another form or a shard attempt named twice."""
    picked: dict[int, tuple[int, str, str]] = {}
    seen: dict[tuple[int, int], str] = {}
    for name in sorted(names):
        match = SHARD_ARTIFACT_RE.fullmatch(name)
        if match is None:
            raise ReportError(f"artifact {name} is not "
                              "suite-timing-shard-<n>-attempt-<a>-<success|failure>")
        shard, attempt, status = int(match[1]), int(match[2]), match[3]
        if (shard, attempt) in seen:
            raise ReportError(f"artifacts {seen[shard, attempt]} and {name} are both "
                              f"shard {shard} attempt {attempt}")
        seen[shard, attempt] = name
        if shard not in picked or attempt > picked[shard][0]:
            picked[shard] = (attempt, status, name)
    return picked


def join_reports(reports: Sequence[dict], count: int) -> dict:
    """One report of the `count` shard reports; raise `ReportError` when they are not
    exactly shards 1 to `count` of `count` or one member is in two of them."""
    if len(reports) != count:
        raise ReportError(f"{len(reports)} shard reports, expected {count}")
    by_shard: dict[int, dict] = {}
    for shard_report in reports:
        if shard_report["shard_count"] != count:
            raise ReportError(f"shard {shard_report['shard']} is of {shard_report['shard_count']}"
                              f" shards, expected {count}")
        if shard_report["shard"] in by_shard:
            raise ReportError(f"shard {shard_report['shard']} is reported twice")
        by_shard[shard_report["shard"]] = shard_report
    if sorted(by_shard) != list(range(1, count + 1)):
        raise ReportError(f"the shards are {sorted(by_shard)}, not 1 to {count}")
    owner: dict[str, int] = {}
    rows: list[tuple[float, int, int, dict]] = []
    for shard in range(1, count + 1):
        for position, row in enumerate(by_shard[shard]["timings"]):
            if row["member"] in owner:
                raise ReportError(f"member {row['member']} is in shard {owner[row['member']]} "
                                  f"and shard {shard}")
            owner[row["member"]] = shard
            rows.append((-row["seconds"], shard, position, row))
    rows.sort(key=lambda entry: entry[:3])
    ordered = [by_shard[shard] for shard in range(1, count + 1)]
    return {
        "version": REPORT_VERSION,
        "members": sum(r["members"] for r in ordered),
        "passed": sum(r["passed"] for r in ordered),
        "failed": sum(r["failed"] for r in ordered),
        "jobs": max(r["jobs"] for r in ordered),
        "shard_count": count,
        "wall_seconds": max(r["wall_seconds"] for r in ordered),
        "member_seconds": sum(r["member_seconds"] for r in ordered),
        "cpu_seconds": round(sum(r["cpu_seconds"] for r in ordered), 1),
        "timings": [entry[3] for entry in rows],
        "shard_summaries": [{"shard": r["shard"], "members": r["members"],
                             "failed": r["failed"], "wall_seconds": r["wall_seconds"]}
                            for r in ordered],
    }


def _say(text: str) -> None:
    print(f"suite-timing: {text}")


def _shard_verdicts(shards_dir: Path, count: int) -> tuple[dict[int, dict], list[str], list[int]]:
    """The valid report of each shard that has one, the line of each shard 1 to `count` and
    the numbers of the shards that failed; raise `ReportError` for the artifact set."""
    names = sorted(entry.name for entry in shards_dir.iterdir()
                   if entry.is_dir()) if shards_dir.is_dir() else []
    picked = pick_artifacts(names)
    for shard in sorted(picked):
        if shard > count:
            raise ReportError(f"artifact {picked[shard][2]} is shard {shard}, "
                              f"the workflow declares {count}")
    reports: dict[int, dict] = {}
    lines: list[str] = []
    failed: list[int] = []
    for shard in range(1, count + 1):
        head = f"shard {shard} of {count}"
        if shard not in picked:
            lines.append(f"{head} failed: it wrote no report")
            failed.append(shard)
            continue
        _, status, name = picked[shard]
        try:
            report = load_shard_report(shards_dir / name / SHARD_REPORT)
            if (report["shard"], report["shard_count"]) != (shard, count):
                raise ReportError(f"shard {report['shard']} of {report['shard_count']} in "
                                  f"artifact {name}, expected {shard} of {count}")
        except ReportError as error:
            lines.append(f"{head} failed: its report is invalid: {error}")
            failed.append(shard)
            continue
        reports[shard] = report
        if report["failed"] > 0:
            names_failed = ", ".join(row["member"] for row in report["timings"]
                                     if not row["passed"])
            lines.append(f"{head} failed: {report['failed']} of {report['members']} members "
                         f"failed: {names_failed}")
            failed.append(shard)
        elif status == "failure":
            lines.append(f"{head} failed: its job had failed when it uploaded a passing report")
            failed.append(shard)
        else:
            lines.append(f"{head} passed: {report['members']} members in "
                         f"{report['wall_seconds']:g}s")
    return reports, lines, failed


def _join(args: argparse.Namespace) -> int:
    try:
        count = declared_shard_count(args.workflow.read_text(encoding="utf-8"), args.shard_job)
    except (OSError, UnicodeDecodeError) as error:
        _say(f"{args.workflow}: cannot read: {error}")
        return 1
    except ReportError as error:
        _say(f"{args.workflow}: {error}")
        return 1
    try:
        reports, lines, failed = _shard_verdicts(args.shards_dir, count)
    except ReportError as error:
        _say(str(error))
        return 1
    for line in lines:
        _say(line)
    joined_ok = True
    if len(reports) == count:
        try:
            joined = join_reports([reports[shard] for shard in range(1, count + 1)], count)
        except ReportError as error:
            _say(str(error))
            joined_ok = False
        else:
            suite_runner.write_report(args.out, joined)
    if failed:
        _say(f"failed shards: {', '.join(str(shard) for shard in failed)}")
        return 1
    if not joined_ok:
        return 1
    if args.needs_result != "success":
        _say(f"the shard jobs concluded {args.needs_result} though every shard uploaded a "
             "passing report from a passing job")
        _say(f"unconfirmed shards: {', '.join(str(shard) for shard in range(1, count + 1))}")
        return 1
    _say("every shard passed")
    return 0


class _Unreadable(Exception):
    """An argument or listing `observed` cannot use; the message is the reason."""


def _positive_seconds(name: str, text: str) -> float:
    try:
        value = float(text)
    except ValueError:
        raise _Unreadable(f"{name} {text!r} is not a number") from None
    if not math.isfinite(value) or value <= 0:
        raise _Unreadable(f"{name} {text!r} is not a finite number above 0")
    return value


def _observed_arguments(args: argparse.Namespace) -> tuple[int, float, float]:
    if _SLUG_RE.fullmatch(args.repo) is None:
        raise _Unreadable(f"--repo {args.repo!r} is not <owner>/<name>")
    if _SHA_RE.fullmatch(args.merge) is None:
        raise _Unreadable(f"--merge {args.merge!r} is not 40 lowercase hex digits")
    try:
        runs = int(args.runs)
    except ValueError:
        raise _Unreadable(f"--runs {args.runs!r} is not an integer") from None
    if runs < 1:
        raise _Unreadable(f"--runs {args.runs!r} is below 1")
    return (runs, _positive_seconds("--before-seconds", args.before_seconds),
            _positive_seconds("--target-seconds", args.target_seconds))


def _listed_runs(page: object) -> list[dict]:
    runs = page.get("workflow_runs") if isinstance(page, dict) else None
    if not isinstance(runs, list) or not all(
            isinstance(run, dict) and isinstance(run.get("id"), int)
            and not isinstance(run.get("id"), bool) and isinstance(run.get("head_sha"), str)
            and isinstance(run.get("created_at"), str) for run in runs):
        raise _Unreadable("a run listing is not an object with a list of runs")
    return runs


def _window(slug: str, branch: str, merge: str, runs: int) -> list[dict] | None:
    """The first `runs` runs from the merge run on, or None while there are fewer or no merge run."""
    listing = f"repos/{slug}/actions/workflows/ci.yaml/runs?branch={quote(branch, safe='')}&event=push"
    at_merge = [run for run in _listed_runs(forge_api.api_get(f"{listing}&head_sha={merge}&per_page=100"))
                if run["head_sha"] == merge]
    if not at_merge:
        return None
    first = min(at_merge, key=lambda run: (run["created_at"], run["id"]))
    pages = forge_api.api_pages(f"{listing}&created=>={first['created_at']}&per_page=100")
    found = {run["id"]: run for page in pages for run in _listed_runs(page)}
    window = sorted(found.values(), key=lambda run: (run["created_at"], run["id"]))
    return window[:runs] if len(window) >= runs else None


def _time(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _first_attempt_jobs(slug: str, run_id: int) -> list[dict]:
    listing = forge_api.api_get(f"repos/{slug}/actions/runs/{run_id}/attempts/1/jobs?per_page=100")
    jobs = listing.get("jobs") if isinstance(listing, dict) else None
    if not isinstance(jobs, list) or not all(isinstance(job, dict) for job in jobs):
        raise _Unreadable(f"run {run_id}: the jobs listing is not an object with a list of jobs")
    return jobs


def _wall(jobs: list[dict]) -> tuple[float, object] | str:
    """(wall seconds, the final job's conclusion) of one first attempt, or why it cannot be timed."""
    finals = [job for job in jobs if job.get("name") == FINAL_JOB]
    shards = [job for job in jobs if str(job.get("name", "")).startswith(SHARD_JOB_PREFIX)]
    if not finals or not shards:
        return f"the {FINAL_JOB} job or its shard jobs are absent"
    if any(job.get("status") != "completed" for job in (finals[0], *shards)):
        return f"the {FINAL_JOB} job or a shard job has not completed"
    ended = _time(finals[0].get("completed_at"))
    started = [_time(job.get("started_at")) for job in shards]
    if ended is None or None in started:
        return "a job time is missing or unreadable"
    return (ended - min(started)).total_seconds(), finals[0].get("conclusion")


def _observed(args: argparse.Namespace) -> int:
    runs, before, target = _observed_arguments(args)
    window = _window(args.repo, args.branch, args.merge, runs)
    if window is None:
        return _observation("not_yet", [], target)
    rows: list[dict] = []
    state = "met"
    for run in window:
        measured = _wall(_first_attempt_jobs(args.repo, run["id"]))
        if isinstance(measured, str):
            if run.get("status") == "completed":
                print(f"suite-timing: run {run['id']}: {measured}", file=sys.stderr)
                state = "not_met"
            elif state == "met":
                state = "not_yet"
            continue
        wall, conclusion = measured
        rows.append({"run": run["id"], "head_sha": run["head_sha"], "wall_seconds": wall,
                     "before_seconds": before, "change_seconds": wall - before,
                     "conclusion": conclusion})
    if state == "met":
        median = statistics.median(row["wall_seconds"] for row in rows)
        state = "met" if median < target else "not_met"
        return _observation(state, rows, target, median)
    return _observation(state, rows, target)


def _observation(state: str, rows: list[dict], target: float, median: float | None = None) -> int:
    sys.stdout.write(json.dumps({"state": state, "runs": rows, "median_seconds": median,
                                 "target_seconds": target}) + "\n")
    return {"met": 0, "not_met": 1, "not_yet": NOT_YET_EXIT}[state]


def _threshold(text: str) -> float:
    try:
        value = float(text)
    except ValueError:
        raise argparse.ArgumentTypeError(f"{text!r} is not a number") from None
    if not math.isfinite(value) or value < 0:
        raise argparse.ArgumentTypeError(f"{text!r} is not a finite number of at least 0")
    return value


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="suite-timing")
    commands = parser.add_subparsers(dest="command", required=True)
    compare_parser = commands.add_parser("compare")
    compare_parser.add_argument("--head", type=Path, required=True)
    compare_parser.add_argument("--base", type=Path, required=True)
    compare_parser.add_argument("--base-label", required=True)
    compare_parser.add_argument("--threshold", type=_threshold, default=DEFAULT_THRESHOLD)
    join_parser = commands.add_parser("join")
    join_parser.add_argument("--workflow", type=Path, required=True)
    join_parser.add_argument("--shard-job", required=True)
    join_parser.add_argument("--shards-dir", type=Path, required=True)
    join_parser.add_argument("--out", type=Path, required=True)
    join_parser.add_argument("--needs-result", required=True)
    observed_parser = commands.add_parser("observed")
    for flag in ("--repo", "--branch", "--merge", "--runs", "--before-seconds", "--target-seconds"):
        observed_parser.add_argument(flag, required=True)
    args = parser.parse_args(argv)
    if args.command == "join":
        return _join(args)
    if args.command == "observed":
        try:
            return _observed(args)
        except (_Unreadable, forge_api.ForgeError) as error:
            print(f"suite-timing: {error}", file=sys.stderr)
            return 2
    try:
        head = load_report(args.head)
    except ReportError as error:
        print(f"suite-timing: {error}", file=sys.stderr)
        return 2
    comparison = None
    try:
        comparison = compare(load_report(args.base), head)
    except ReportError as error:
        print(f"suite-timing: base: {error}", file=sys.stderr)
    lines = [summary_line(head, comparison, threshold=args.threshold,
                          base_label=args.base_label),
             "", "| Slowest tests | Seconds |", "|---|---:|"]
    lines += [f"| {row['member']} | {row['seconds']:.1f} |"
              for row in head["timings"][:SLOWEST_ROWS]]
    sys.stdout.write("\n".join(lines) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
