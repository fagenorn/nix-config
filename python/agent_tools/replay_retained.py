"""`replay-retained`: replay a retained review bundle from its directory alone (issue 249).

The command takes exactly two required options and no other, a help option
included: `--fixtures-dir` and `--expected-anchor-sha256`. It calls
`review_replay.replay` with the three real pin constants. It runs no Git and
asks no budget authority.

| Outcome | Exit | stdout | stderr |
|---|---|---|---|
| Every outcome measured, over budget included | 0 | `canonical_bytes(result)` | empty |
| Any outcome unavailable | 2 | empty | `replay-retained: projection_unavailable: <ids joined by ",">` |
| A refusal | 2 | empty | `replay-retained: invalid: <code>` |

`<code>` is `usage` for a command line the parser refuses, the `code` of a
`WitnessError`, `EstimateError`, `ContributionError` or `Issue100Error`, and
`io_error` for an `OSError`. Nothing else is caught: any other exception leaves
with its traceback (RP8).
"""
from __future__ import annotations

import argparse
from pathlib import Path
import sys
from typing import Sequence

from agent_tools.review_forecast import canonical_bytes
from agent_tools.review_issue100 import ISSUE_100_PINS, Issue100Error
from agent_tools.review_issue121 import ISSUE_121_PINS, ContributionError
from agent_tools.review_replay import ReplayUnavailable, replay
from agent_tools.review_task7 import TASK7_PINS, EstimateError
from agent_tools.review_witness import WitnessError

_PROG = "replay-retained"


class _Usage(Exception):
    """The command line is not the two required options."""


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise _Usage(message)


def main(argv: Sequence[str] | None = None) -> int:
    parser = _Parser(prog=_PROG, add_help=False, allow_abbrev=False)
    parser.add_argument("--fixtures-dir", required=True, type=Path)
    parser.add_argument("--expected-anchor-sha256", required=True)
    try:
        args = parser.parse_args(argv)
        result = replay(args.fixtures_dir, args.expected_anchor_sha256, task7_pins=TASK7_PINS,
                        issue121_pins=ISSUE_121_PINS, issue100_pins=ISSUE_100_PINS)
    except ReplayUnavailable as exc:
        reason = "projection_unavailable: " + ",".join(exc.ids)
    except _Usage:
        reason = "invalid: usage"
    except (WitnessError, EstimateError, ContributionError, Issue100Error) as exc:
        reason = f"invalid: {exc.code}"
    except OSError:
        reason = "invalid: io_error"
    else:
        sys.stdout.buffer.write(canonical_bytes(result))
        return 0
    sys.stderr.write(f"{_PROG}: {reason}\n")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
