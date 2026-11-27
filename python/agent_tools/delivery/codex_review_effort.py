"""The one declaration of the Codex review effort, and the copies that carry it as prose.

`EFFORT` is the value the independent review passes to `codex-companion` and the value the
codex-collaboration skill tells its reader to pass and to require back as `runtime.reasoningEffort`.
The Python code and the tests read `EFFORT`. Three places are prose or patch text that no code
reads, so this module rewrites them from `EFFORT` (`--write`) and names any that disagree
(`--check`, the default):

- the skill's `SKILL.md` (the review command and the validation text),
- the skill's `evals/evals.json` (the same two phrases in each reviewing case),
- the added `tests/reviewer-detach.test.mjs` in `patches/agent-plugins/codex-plugin-cc.patch`.

Changing the effort is one edit: set `EFFORT`, run
`PYTHONPATH=python python3 -m agent_tools.delivery.codex_review_effort --write`, and
`home/common/agent-skills/tests/test_codex_review_effort.py` fails until the copies agree.

`--write` only rewrites the files named above, and refuses (exit 2) when a pattern finds no
occurrence, so a reworded copy cannot silently drop out of the declaration.
"""

from __future__ import annotations

import argparse
import re
import sys
from collections.abc import Sequence
from pathlib import Path

EFFORT = "high"

SKILL = "home/common/claude-code/skills/codex-collaboration/SKILL.md"
EVALS = "home/common/claude-code/skills/codex-collaboration/evals/evals.json"
PATCH = "patches/agent-plugins/codex-plugin-cc.patch"

_PATCH_HUNK_HEADER = "diff --git a/tests/reviewer-detach.test.mjs b/tests/reviewer-detach.test.mjs\n"
_NEXT_DIFF = "\ndiff --git "

# (head, tail): the effort word sits between them; `head` and `tail` are kept as written.
_COMMAND = (r"--effort ", r"(?![\w-])")
_SKILL_RESULT = (r"`runtime\.reasoningEffort` `", r"`")
_EVAL_RESULT = (r"runtime\.reasoningEffort ", r"(?![\w-])")
_PATCH_COMMAND = (r'"--effort", "', r'"')
_PATCH_RESULT = (r'reasoningEffort: "', r'"')

_FILE_RULES = {
    SKILL: (_COMMAND, _SKILL_RESULT),
    EVALS: (_COMMAND, _EVAL_RESULT),
    PATCH: (_PATCH_COMMAND, _PATCH_RESULT),
}


class CopyError(Exception):
    """A copy lacks a phrase the declaration is rendered into."""


def _rewrite(text: str, rules: Sequence[tuple[str, str]], effort: str, where: str) -> str:
    for head, tail in rules:
        pattern = re.compile(rf"(?P<head>{head})[a-z]+(?P<tail>{tail})")
        text, count = pattern.subn(lambda m: m["head"] + effort + m["tail"], text)
        if not count:
            raise CopyError(f"{where}: no occurrence of /{head}<effort>{tail}/")
    return text


def render(path: str, text: str, effort: str = EFFORT) -> str:
    """`text` of the copy at `path` (relative to the repository root) carrying `effort`."""
    if not re.fullmatch(r"[a-z]+", effort):
        raise CopyError(f"effort {effort!r} is not a lowercase word")
    rules = _FILE_RULES[path]
    if path != PATCH:
        return _rewrite(text, rules, effort, path)
    if text.count(_PATCH_HUNK_HEADER) != 1:
        raise CopyError(f"{path}: expected exactly one {_PATCH_HUNK_HEADER.strip()!r}")
    before, hunk_and_rest = text.split(_PATCH_HUNK_HEADER, 1)
    hunk, separator, rest = hunk_and_rest.partition(_NEXT_DIFF)
    hunk = _rewrite(hunk, rules, effort, path)
    return before + _PATCH_HUNK_HEADER + hunk + separator + rest


def disagreements(root: Path, effort: str = EFFORT) -> list[str]:
    """The copies under `root` (relative paths) that do not carry `effort`."""
    return [
        path for path in _FILE_RULES
        if render(path, (root / path).read_text(encoding="utf-8"), effort)
        != (root / path).read_text(encoding="utf-8")
    ]


def write(root: Path, effort: str = EFFORT) -> list[str]:
    """Rewrite every copy under `root` to carry `effort`; the relative paths that changed."""
    changed = []
    for path in _FILE_RULES:
        current = (root / path).read_text(encoding="utf-8")
        wanted = render(path, current, effort)
        if wanted != current:
            (root / path).write_text(wanted, encoding="utf-8")
            changed.append(path)
    return changed


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="codex_review_effort", description=__doc__.split("\n")[0])
    parser.add_argument("--write", action="store_true", help="rewrite the copies from EFFORT")
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[3],
                        help="repository root (default: the checkout this module is in)")
    args = parser.parse_args(argv)
    try:
        if args.write:
            for path in write(args.root):
                print(f"rewrote {path} to effort {EFFORT}")
            return 0
        stale = disagreements(args.root)
    except CopyError as error:
        print(f"codex_review_effort: {error}", file=sys.stderr)
        return 2
    for path in stale:
        print(f"{path} does not carry effort {EFFORT}", file=sys.stderr)
    return 1 if stale else 0


if __name__ == "__main__":
    raise SystemExit(main())
