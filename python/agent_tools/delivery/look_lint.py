"""Refuse an issue body that carries a near miss of the look marker (issue 1141).

Usage: `look-lint --body-file <path|->`; `-` reads the body from stdin.

Prints exactly one JSON line on stdout and nothing on stderr:

    {"command":"look-lint","verdict":"ok","marked":true,"covers":["<what>"],"malformed":[]}
    {"command":"look-lint","verdict":"malformed","marked":false,"covers":[],"malformed":[{"line":3,"text":"<line>"}]}
    {"command":"look-lint","verdict":"error","error":"usage","detail":"<reason>"}

Exit 0 when the body has no near miss (`marked` says whether it carries a look marker), 1 when
it has one or more (`malformed` lists each with its 1-based line number, even beside a valid
marker), 2 on a usage error: no arguments, an unknown argument, a path that cannot be opened,
or bytes that are not UTF-8 (file or stdin). A near miss is a criterion-shaped line
(an optional list bullet then bracket groups) outside code fences and inline code spans that is
not a marker and says `before[\\s_-]*merg` after its bracket groups or beside a `[human]` group,
any case (`look_marker.near_misses`); prose is never one.

This module reads no network, runs no subprocess and reads no environment.
"""
import argparse
import json
import sys
from pathlib import Path
from typing import Any, NoReturn

from agent_tools.delivery import look_marker as lm

COMMAND = "look-lint"
USAGE = 2


class UsageError(Exception):
    """The arguments or the body break the contract; carries the detail."""


class Parser(argparse.ArgumentParser):
    def error(self, message: str) -> NoReturn:
        raise UsageError(message)


def build_parser() -> argparse.ArgumentParser:
    parser = Parser(prog=COMMAND, description=__doc__)
    parser.add_argument("--body-file", required=True, help="the issue body file, or - for stdin")
    return parser


def emit(out: dict[str, Any]) -> None:
    print(json.dumps(out, sort_keys=False, separators=(",", ":")))


def read_body(path: str) -> str:
    try:
        raw = sys.stdin.buffer.read() if path == "-" else Path(path).read_bytes()
        return raw.decode("utf-8")
    except (OSError, UnicodeDecodeError) as error:
        raise UsageError(f"cannot read --body-file {path}: {error}") from None


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    try:
        body = read_body(build_parser().parse_args(argv).body_file)
    except UsageError as error:
        emit({"command": COMMAND, "verdict": "error", "error": "usage", "detail": str(error)})
        return USAGE
    look = lm.read_look(body)
    misses = lm.near_misses(body)
    emit(
        {
            "command": COMMAND,
            "verdict": "malformed" if misses else "ok",
            "marked": look.marked,
            "covers": list(look.covers),
            "malformed": [{"line": miss.line, "text": miss.text} for miss in misses],
        }
    )
    return 1 if misses else 0


if __name__ == "__main__":
    sys.exit(main())
