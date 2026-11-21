"""`engine`: run the delivery engine's commands (#1508).

`engine check [--procedures <dir>]` reads the procedure files of a directory
(default: the package's `procedures` directory) and prints one line of compact
sorted-key JSON to stdout, starting no process and opening no socket:

- exit 0: `{"procedures": [<names>], "verdict": "ok"}`;
- exit 1: `{"refusals": [{"defect", "detail", "procedure", "step"}, ...],
  "verdict": "refused"}`, ordered by procedure name, phase, then step position;
- exit 2, stdout empty and one stderr line: a usage error, `--procedures` not a
  directory, a directory with no procedure file, or an invalid
  `command_verdicts.json`.

The procedure format and every refusal code are `procedure_check`'s contract.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from agent_tools.delivery import procedure_check

PROCEDURES_DIR = Path(__file__).with_name("procedures")


def compact(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n"


class UsageError(Exception):
    pass


class _Parser(argparse.ArgumentParser):
    def error(self, message: str):
        raise UsageError(message)


def build_parser() -> argparse.ArgumentParser:
    parser = _Parser(prog="engine", description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    check_parser = commands.add_parser(
        "check", help="refuse a malformed procedure by step and defect")
    check_parser.add_argument("--procedures", type=Path, default=PROCEDURES_DIR)
    return parser


def _usage(message: str) -> int:
    sys.stderr.write("engine: " + " ".join(message.split()) + "\n")
    return 2


def main(argv: list[str] | None = None) -> int:
    try:
        args = build_parser().parse_args(argv)
    except UsageError as error:
        return _usage(str(error))
    if not args.procedures.is_dir():
        return _usage(f"--procedures is not a directory: {args.procedures}")
    try:
        commands = procedure_check.load_commands()
        result = procedure_check.check_directory(args.procedures, commands)
    except (procedure_check.DeclarationError, ValueError) as error:
        return _usage(str(error))
    if result.refusals:
        sys.stdout.write(compact({"refusals": [r.as_json() for r in result.refusals],
                                  "verdict": "refused"}))
        return 1
    sys.stdout.write(compact({"procedures": list(result.procedures), "verdict": "ok"}))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
