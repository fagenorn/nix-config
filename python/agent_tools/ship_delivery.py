"""The ship-delivery executable's argv and output boundary."""

import argparse
import json
from pathlib import Path
import sys

from agent_tools.ship_delivery_compile import compile_delivery, load_json


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="ship-delivery", description=(
        "Compile factual recipes into canonical ship checkpoints or summaries. "
        "No external effect or ledger write is performed. "
        "Recipe API: ~/.agents/share/ship-delivery.md (source: python/ship-delivery.md)."))
    parser.add_argument("mode", choices=("checkpoint", "summary"))
    parser.add_argument("--context", required=True, help="Unchanged ship-handoff/v2 or delivery_remainder JSON")
    parser.add_argument("--prior", action="append", default=[], help="Previous canonical payload (repeatable)")
    parser.add_argument("--input", default="-", help="Recipe JSON path, or - for stdin")
    parser.add_argument("--output", help="Retain payload in a new runtime file; stdout still contains it")
    args = parser.parse_args(argv)
    try:
        context = load_json(Path(args.context).read_text(encoding="utf-8"))
        prior = [load_json(Path(path).read_text(encoding="utf-8")) for path in args.prior]
        raw = sys.stdin.read() if args.input == "-" else Path(args.input).read_text(encoding="utf-8")
        payload = compile_delivery(args.mode, context, load_json(raw), prior=prior)
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n"
        if args.output:
            with Path(args.output).open("x", encoding="utf-8") as output:
                output.write(encoded)
    except (OSError, ValueError) as error:
        print(f"ship-delivery: {error}", file=sys.stderr)
        return 2
    sys.stdout.write(encoded)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
