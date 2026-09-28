"""The `promotion` command: validate promotion documents (#127).

`promotion validate --input <path>` reads one document, judges its shape with
`promotion_schema.validate_document` and prints `{"valid":true}`. It resolves
nothing and writes nothing.

Every printed document is one canonical JSON line. Exit 0 is a document; 3 is
a gate refusal and 2 a tool or structural failure, each printing exactly one
`error` object; an argparse usage error exits 2 with no JSON. `main` is the one
exception boundary (D12). Policy lives in `promotion_schema`, not here (D2).
"""

import argparse
import json
import sys

from agent_tools.promotion_schema import (COMMAND_NAME, INTERNAL_FAILURE_MESSAGE, Refusal,
                                          load_strict, validate_document, violation)


def read_document(path: str) -> dict:
    """The JSON object at `path`, strictly loaded (D30); raises `Refusal`."""
    try:
        with open(path, encoding="utf-8") as handle:
            text = handle.read()
    except (OSError, UnicodeError):
        raise Refusal("unreadable_input", [violation("", "the input file cannot be read")])
    try:
        document = load_strict(text)
    except ValueError:
        raise Refusal("invalid_document", [violation("", "the input is not strict JSON")])
    if not isinstance(document, dict):
        raise Refusal("invalid_document", [violation("", "must be an object")])
    return document


def render(document) -> str:
    """The canonical line: sorted, compact, ASCII-escaped, finite JSON plus a newline."""
    return json.dumps(document, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
                      allow_nan=False) + "\n"


def emit(document) -> int:
    sys.stdout.write(render(document))
    return 0


def emit_refusal(refusal: Refusal) -> int:
    sys.stdout.write(render({"error": {"code": refusal.code,
                                       "candidate_id": refusal.candidate_id,
                                       "state": refusal.state,
                                       "violations": refusal.violations}}))
    return refusal.exit_code


def run_validate(args) -> int:
    document = read_document(args.input)
    violations = validate_document(document)
    if violations:
        raise Refusal("invalid_document", violations)
    return emit({"valid": True})


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog=COMMAND_NAME,
                                     description="Validate promotion documents.")
    subcommands = parser.add_subparsers(dest="subcommand", required=True)
    validate = subcommands.add_parser(
        "validate", help="judge one document's shape; resolves and writes nothing")
    validate.add_argument("--input", required=True, metavar="PATH",
                          help="a draft, candidate or evaluation document")
    validate.set_defaults(handler=run_validate)
    return parser


def main(argv=None) -> int:
    try:
        args = build_parser().parse_args(argv)
        return args.handler(args)
    except SystemExit:
        raise
    except Refusal as refusal:
        return emit_refusal(refusal)
    except Exception as error:  # the one boundary (D12)
        print(f"{COMMAND_NAME}: {error!r}", file=sys.stderr)
        return emit_refusal(Refusal("internal_failure",
                                    [violation("", INTERNAL_FAILURE_MESSAGE)]))


if __name__ == "__main__":
    raise SystemExit(main())
