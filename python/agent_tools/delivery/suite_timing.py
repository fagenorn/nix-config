"""Compare a suite timing report with the base branch's and say when the suite grew (issue 1385).

Usage: `python -m agent_tools.delivery.suite_timing compare --head <path> --base <path>
--base-label <label> [--threshold <seconds>]`

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
threshold is within it. Rounding is for display only.

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
"""

import argparse
import json
import math
import statistics
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from agent_tools import canonical

DEFAULT_THRESHOLD = 60.0
FACTOR_FLOOR_SECONDS = 1.0
SLOWEST_ROWS = 10
REPORT_VERSION = 1


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
    return (isinstance(value, (int, float)) and not isinstance(value, bool)
            and math.isfinite(value) and value >= 0)


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


def compare(base: dict, head: dict) -> Comparison:
    factor = speed_factor(base, head)
    base_seconds = _seconds_by_member(base)
    largest_member = ""
    largest_delta = -math.inf
    for row in head["timings"]:
        delta = row["seconds"] - factor * base_seconds.get(row["member"], 0.0)
        if delta > largest_delta:
            largest_member, largest_delta = row["member"], delta
    return Comparison(
        base_seconds=base["member_seconds"],
        head_seconds=head["member_seconds"],
        factor=factor,
        growth=head["member_seconds"] - factor * base["member_seconds"],
        largest_member=largest_member,
        largest_delta=largest_delta,
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
    args = parser.parse_args(argv)
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
