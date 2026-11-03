"""Thin source-command boundary for review feasibility: projection, gate, confirmation and forecast writing."""
from __future__ import annotations

import argparse
from pathlib import Path
import sys
from typing import Sequence

from agent_tools.review_actual import GenerationError, InvocationError, _run_git
from agent_tools.review_budget import BudgetError, describe
from agent_tools.review_forecast import ForecastError, canonical_bytes, read_regular
from agent_tools.review_forecast_writer import HELP, write_forecast
from agent_tools.review_gate import confirm, gate
from agent_tools.review_pack import ReviewPackError
from agent_tools.review_projection import project, validate_result


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise ForecastError(message)


def _read_input(value: str, bound: int) -> bytes:
    if value == "-":
        return sys.stdin.buffer.read(bound + 1)
    path = Path(value).absolute()
    # Bound before decoding, and never follow an input symlink.
    return read_regular(path.parent, path.name, bound)


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
    summary = commands.add_parser("gate")
    summary.add_argument("--plan", required=True, type=Path)
    summary.add_argument("--base", required=True)
    summary.add_argument("--head", required=True)
    summary.add_argument("--completed-through", required=True, type=int)
    summary.add_argument("--save-dir", type=Path)
    confirmation = commands.add_parser("confirm")
    confirmation.add_argument("--plan", required=True, type=Path)
    confirmation.add_argument("--base", required=True)
    confirmation.add_argument("--input", required=True)
    forecast = commands.add_parser("forecast", help="write the forecast blocks from an estimate",
                                   description=HELP, formatter_class=argparse.RawDescriptionHelpFormatter)
    forecast.add_argument("--plan", required=True, type=Path)
    forecast.add_argument("--base", required=True)
    forecast.add_argument("--spec", required=True, type=Path)
    forecast.add_argument("--input", required=True)
    try:
        args = parser.parse_args(argv)
        if args.command == "gate":
            code, summary_bytes = gate(args.plan, args.base, args.head, args.completed_through,
                                       save_dir=args.save_dir)
            sys.stdout.buffer.write(summary_bytes)
            return code
        if args.command == "confirm":
            raw = _read_input(args.input, describe("review-package").report_wire_max_bytes)
            code, summary_bytes = confirm(args.plan, args.base, raw)
            sys.stdout.buffer.write(summary_bytes)
            return code
        if args.command == "project":
            plan = args.plan.absolute()
            repo = Path(_run_git(plan.parent, "rev-parse", "--show-toplevel").strip())
            value = project(repo, plan, args.base, args.head, args.completed_through, args.package_name)
            sys.stdout.buffer.write(canonical_bytes(value))
            return 0 if value["state"] == "complete" else 3
        if args.command == "forecast":
            authority = describe("review-package")
            raw = _read_input(args.input, authority.report_wire_max_bytes)
            plan = args.plan.absolute()
            repo = Path(_run_git(plan.parent, "rev-parse", "--show-toplevel").strip())
            written = write_forecast(repo, plan, args.base, args.spec.absolute(), raw, authority)
            sys.stdout.buffer.write(canonical_bytes({"written": written}))
            return 0
        authority = describe("review-package")
        raw = _read_input(args.input, authority.report_wire_max_bytes)
        sys.stdout.buffer.write(validate_result(raw, args.producer_exit, authority))
        return 0
    except (ForecastError, GenerationError, InvocationError, BudgetError, ReviewPackError,
            OSError, ValueError, TypeError, KeyError, IndexError) as exc:
        message = str(exc).replace("\n", " ")[:400]
        sys.stderr.write(f"review-feasibility: {message}\n")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
