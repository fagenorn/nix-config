"""Compare a model's baseline replies with neuron-steered ones, outside the server.

  omlx-steer "L14 N8949 +1" "L13 N7956 -1"
  omlx-steer --model mlx-community/Qwen3.5-4B-bf16 --scale 0.5 --prompt "Hi" "L14 N8949 +1"

Uses oMLX's patched neuron_steering module (patches/omlx/neuron-steering.patch),
so a result here is what the matching `steer.<preset>` entry in omlx.nix serves.
"""

import argparse
import re
import sys

from mlx_lm import generate, load
from omlx.patches.neuron_steering import CALIBRATION_PROMPTS, steer

ENTRY = re.compile(r"L(\d+) N(\d+) ([+-]?\d+(?:\.\d+)?)")


def parse_entry(text):
    match = ENTRY.fullmatch(text.strip())
    if match is None:
        raise argparse.ArgumentTypeError(f'"{text}" is not "L<layer> N<neuron> <dose>"')
    return int(match[1]), int(match[2]), float(match[3])


def reply(model, tokenizer, prompt, max_tokens):
    text = tokenizer.apply_chat_template(
        [{"role": "user", "content": prompt}],
        add_generation_prompt=True,
        enable_thinking=False,
        tokenize=False,
    )
    return generate(model, tokenizer, text, max_tokens=max_tokens).strip()


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("entries", nargs="+", type=parse_entry, metavar='"L<layer> N<neuron> <dose>"')
    parser.add_argument("--model", default="mlx-community/Qwen3.5-4B-bf16", help="HF repo or local path")
    parser.add_argument("--scale", type=float, default=1.0, help="multiply every dose")
    parser.add_argument("--prompt", action="append", help="repeatable; defaults to the calibration prompts")
    parser.add_argument("--max-tokens", type=int, default=200)
    parser.add_argument("--no-baseline", action="store_true")
    args = parser.parse_args()

    entries = [(layer, neuron, dose * args.scale) for layer, neuron, dose in args.entries]
    prompts = args.prompt or list(CALIBRATION_PROMPTS)
    model, tokenizer = load(args.model)
    baseline = {} if args.no_baseline else {p: reply(model, tokenizer, p, args.max_tokens) for p in prompts}
    steer(model, tokenizer, entries)
    for prompt in prompts:
        print("=" * 72, f"\n{prompt}")
        if prompt in baseline:
            print(f"--- baseline ---\n{baseline[prompt]}")
        print(f"--- steered ---\n{reply(model, tokenizer, prompt, args.max_tokens)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
