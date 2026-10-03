"""Thin source-command boundary for read-only review feasibility."""
from __future__ import annotations

import argparse
from pathlib import Path
import sys
from typing import Sequence

from agent_tools.review_actual import GenerationError, InvocationError, _run_git
from agent_tools.review_budget import BudgetError, describe
from agent_tools.review_forecast import ForecastError, canonical_bytes, read_regular
from agent_tools.review_pack import ReviewPackError
from agent_tools.review_projection import project, validate_result


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise ForecastError(message)


def main(argv: Sequence[str] | None = None) -> int:
    parser = _Parser(prog="review-feasibility")
    commands = parser.add_subparsers(dest="command", required=True)
    projection = commands.add_parser("project")
    projection.add_argument("--plan", required=True, type=Path)
    projection.add_argument("--base", required=True)
    projection.add_argument("--head", required=True)
    projection.add_argument("--completed-through", required=True, type=int)
    projection.add_argument("--package-name")
    validation = commands.add_parser("validate-result")
    validation.add_argument("--input", required=True)
    validation.add_argument("--producer-exit", required=True, type=int, choices=(0, 3))
    try:
        args = parser.parse_args(argv)
        if args.command == "project":
            plan = args.plan.absolute()
            repo = Path(_run_git(plan.parent, "rev-parse", "--show-toplevel").strip())
            value = project(repo, plan, args.base, args.head, args.completed_through, args.package_name)
            sys.stdout.buffer.write(canonical_bytes(value))
            return 0 if value["state"] == "complete" else 3
        authority = describe("review-package")
        if args.input == "-":
            raw = sys.stdin.buffer.read(authority.report_wire_max_bytes + 1)
        else:
            path = Path(args.input).absolute()
            # Bound before decoding, and never follow an input symlink.
            raw = read_regular(path.parent, path.name, authority.report_wire_max_bytes)
        sys.stdout.buffer.write(validate_result(raw, args.producer_exit, authority))
        return 0
    except (ForecastError, GenerationError, InvocationError, BudgetError, ReviewPackError,
            OSError, ValueError, TypeError, KeyError, IndexError) as exc:
        message = str(exc).replace("\n", " ")[:400]
        sys.stderr.write(f"review-feasibility: {message}\n")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
