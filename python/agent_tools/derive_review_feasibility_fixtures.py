"""`derive-review-feasibility-fixtures`: derive the retained review bundle into a fresh directory (issue 249).

The command takes exactly six required options and no other, a help option
included: `--issue-121-repo`, `--issue-100-repo`, `--archive-dir`,
`--tool-repo`, `--tool-commit` and `--output-dir`. It asks the budget authority
for the `review-package` description, calls `review_derivation.derive_bundle`
with the three real pin constants, writes `canonical_bytes` of the returned
summary to stdout and exits 0.

A refusal prints `derive-review-feasibility-fixtures: invalid: <code>` to
stderr, writes nothing to stdout and exits 2. `<code>` is `usage` for a
command line the parser refuses, the `code` of a `DerivationError`,
`WitnessError`, `EstimateError`, `ContributionError` or `Issue100Error`,
`budget_unavailable` for a `BudgetError` and `io_error` for an `OSError`.
Nothing else is caught: any other exception leaves with its traceback (RP8).
"""
from __future__ import annotations

import argparse
from pathlib import Path
import sys
from typing import Sequence

from agent_tools.review_budget import BudgetError, describe
from agent_tools.review_derivation import DerivationError, DeriveInputs, derive_bundle
from agent_tools.review_forecast import canonical_bytes
from agent_tools.review_issue100 import ISSUE_100_PINS, Issue100Error
from agent_tools.review_issue121 import ISSUE_121_PINS, ContributionError
from agent_tools.review_task7 import TASK7_PINS, EstimateError
from agent_tools.review_witness import WitnessError

_PROG = "derive-review-feasibility-fixtures"


class _Usage(Exception):
    """The command line is not the six required options."""


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise _Usage(message)


def main(argv: Sequence[str] | None = None) -> int:
    parser = _Parser(prog=_PROG, add_help=False, allow_abbrev=False)
    for option in ("--issue-121-repo", "--issue-100-repo", "--archive-dir", "--tool-repo"):
        parser.add_argument(option, required=True, type=Path)
    parser.add_argument("--tool-commit", required=True)
    parser.add_argument("--output-dir", required=True, type=Path)
    try:
        args = parser.parse_args(argv)
        inputs = DeriveInputs(args.issue_121_repo, args.issue_100_repo, args.archive_dir, args.tool_repo,
                              args.tool_commit, args.output_dir)
        summary = derive_bundle(inputs, task7_pins=TASK7_PINS, issue121_pins=ISSUE_121_PINS,
                                issue100_pins=ISSUE_100_PINS, authority=describe("review-package"))
    except _Usage:
        code = "usage"
    except (DerivationError, WitnessError, EstimateError, ContributionError, Issue100Error) as exc:
        code = exc.code
    except BudgetError:
        code = "budget_unavailable"
    except OSError:
        code = "io_error"
    else:
        sys.stdout.buffer.write(canonical_bytes(summary))
        return 0
    sys.stderr.write(f"{_PROG}: invalid: {code}\n")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
