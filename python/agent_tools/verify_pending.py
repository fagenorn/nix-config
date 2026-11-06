"""verify-pending: the commands over a `verify` block.

`verify-pending lint --input <path|->` prints the verdict as one line of
`json.dumps(verdict, sort_keys=True)` and exits 0 when the block is accepted,
1 when it is refused and 2 on a usage error or an unreadable input path.
"""

import argparse
import json
import sys

from agent_tools.verify_block import lint_block, parse_block


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="verify-pending")
    commands = parser.add_subparsers(dest="command", required=True)
    lint = commands.add_parser("lint", help="check a verify block")
    lint.add_argument("--input", required=True, help="a hold comment or JSON block; - reads stdin")
    return parser


def read_input(path: str) -> str:
    if path == "-":
        return sys.stdin.read()
    with open(path, encoding="utf-8") as handle:
        return handle.read()


def run_lint(args: argparse.Namespace) -> int:
    try:
        text = read_input(args.input)
    except (OSError, UnicodeDecodeError) as error:
        print(f"verify-pending: cannot read {args.input}: {error}", file=sys.stderr)
        return 2
    block, parse_errors = parse_block(text)
    if parse_errors:
        verdict = {"ok": False, "errors": parse_errors, "warnings": []}
    else:
        verdict = lint_block(block)
    print(json.dumps(verdict, sort_keys=True))
    return 0 if verdict["ok"] else 1


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return run_lint(args)


if __name__ == "__main__":
    sys.exit(main())
