"""Command-line entry point for bounded review packages."""
from __future__ import annotations

import argparse
import sys
from typing import Sequence

from agent_tools.review_actual import GenerationError, InvocationError
from agent_tools.review_budget import BudgetError, describe
from agent_tools.review_pack import ReviewPackError, canonical_manifest
from agent_tools.review_publish import build_detail, build_diff

class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise InvocationError(message)

    def exit(self, status: int = 0, message: str | None = None) -> None:
        raise InvocationError(message or "unsupported parser exit")


def _parser() -> _Parser:
    parser = _Parser(prog="review-package", add_help=False)
    parser.add_argument("items", nargs="*")
    parser.add_argument("--detail-input")
    parser.add_argument("--producer")
    parser.add_argument("--issue")
    parser.add_argument("--branch")
    parser.add_argument("--run-id")
    parser.add_argument("--head")
    parser.add_argument("--output")
    return parser


def _mode(args: argparse.Namespace) -> str:
    detail_values = (
        args.detail_input, args.producer, args.issue, args.branch, args.run_id,
        args.head, args.output,
    )
    if args.detail_input is not None:
        if args.items or any(value is None for value in detail_values[:-1]):
            raise InvocationError("invalid detail invocation")
        return "detail"
    if any(value is not None for value in detail_values) or len(args.items) not in {3, 4}:
        raise InvocationError("invalid diff invocation")
    return "diff"


def main(argv: Sequence[str] | None = None) -> int:
    try:
        authority = describe("review-package")
    except BudgetError:
        sys.stderr.write("review-package: validator unavailable\n")
        return 2
    try:
        args = _parser().parse_args(argv)
        mode = _mode(args)
        report, status = (build_detail(args, authority) if mode == "detail"
                          else build_diff(args, authority))
        sys.stdout.buffer.write(authority.validate_report(canonical_manifest(report), "producer"))
        return status
    except InvocationError:
        sys.stderr.write("review-package: invalid invocation\n")
        return 2
    except (GenerationError, BudgetError, ReviewPackError, OSError, ValueError):
        try:
            sys.stdout.buffer.write(authority.validate_report(canonical_manifest(
                {"state": "failed", "artifact": None,
                 "notes": "review package generation failed"}), "producer"))
        except BudgetError:
            sys.stderr.write("review-package: generation failed\n")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
