"""The one declaration of the Codex review effort, and the copies that carry it as prose.

`EFFORT` is the value the independent review passes to `codex-companion` and the value the
codex-collaboration skill tells its reader to pass and to require back as `runtime.reasoningEffort`.
The Python code and the tests read `EFFORT`. Three places are prose or patch text that no code
reads, so this module rewrites them from `EFFORT` (`--write`) and names any that disagree
(`--check`, the default):

- the skill's `SKILL.md` (the review command and the validation text),
- the skill's `evals/evals.json` (the same two phrases in each reviewing case),
- the added `tests/reviewer-detach.test.mjs` in `patches/agent-plugins/codex-plugin-cc.patch`.

Changing the effort is one edit: set `EFFORT`. The Home Manager build installs the skill through
`--render-skill`, so the installed skill follows `EFFORT` with no other step. The checked-in copies
(which the tests and the plugin's own suite read) are brought into line with
`PYTHONPATH=python python3 -m agent_tools.delivery.codex_review_effort --write`;
`home/common/agent-skills/tests/test_codex_review_effort.py` fails until they agree.

`--write` renders every copy before it writes any, so a refusal leaves the tree untouched. When it
changes the plugin patch it also bumps `patchRevision` in `lib/agent-plugins.nix`, because the
advertised plugin version must change with the patch's contents. A copy is refused (exit 2) when a
pattern finds no occurrence or when an occurrence of the phrase carries a value the pattern cannot
rewrite (a quoted value, say), so a reworded copy cannot silently drop out of the declaration;
in the evals each case is checked on its own, so one case cannot hide behind another.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections.abc import Sequence
from pathlib import Path

EFFORT = "high"

SKILL = "home/common/claude-code/skills/codex-collaboration/SKILL.md"
EVALS = "home/common/claude-code/skills/codex-collaboration/evals/evals.json"
PATCH = "patches/agent-plugins/codex-plugin-cc.patch"
PLUGINS_NIX = "lib/agent-plugins.nix"

# The same two skill copies, as paths inside an installed skill directory.
SKILL_DIR_FILES = {SKILL: "SKILL.md", EVALS: "evals/evals.json"}

_PATCH_REVISION = re.compile(r"(?P<head>\bpatchRevision = )(?P<n>\d+)(?P<tail>;)")

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


def _pattern(head: str, tail: str) -> re.Pattern[str]:
    return re.compile(rf"(?P<head>{head})[a-z]+(?P<tail>{tail})")


def _check_occurrences(text: str, rules: Sequence[tuple[str, str]], where: str) -> None:
    """Every place the phrase's head occurs must be one the rewrite will reach."""
    for head, tail in rules:
        heads = len(re.findall(head, text))
        reached = len(_pattern(head, tail).findall(text))
        if heads != reached:
            raise CopyError(
                f"{where}: {heads - reached} of {heads} occurrences of /{head}/ carry a value "
                f"/{head}<effort>{tail}/ does not match")


def _rewrite(text: str, rules: Sequence[tuple[str, str]], effort: str, where: str) -> str:
    _check_occurrences(text, rules, where)
    for head, tail in rules:
        text, count = _pattern(head, tail).subn(lambda m: m["head"] + effort + m["tail"], text)
        if not count:
            raise CopyError(f"{where}: no occurrence of /{head}<effort>{tail}/")
    return text


def _check_eval_cases(text: str, rules: Sequence[tuple[str, str]], where: str) -> None:
    """Each case carries both phrases or neither, and every occurrence in it is rewritable."""
    for case in json.loads(text)["evals"]:
        strings = "\n".join(value for value in case.values() if isinstance(value, str))
        label = f"{where}: case {case.get('name')!r}"
        _check_occurrences(strings, rules, label)
        counts = [len(re.findall(head, strings)) for head, _ in rules]
        if any(counts) and not all(counts):
            raise CopyError(f"{label}: carries the command or the validation text but not both")


def render(path: str, text: str, effort: str = EFFORT) -> str:
    """`text` of the copy at `path` (relative to the repository root) carrying `effort`."""
    if not re.fullmatch(r"[a-z]+", effort):
        raise CopyError(f"effort {effort!r} is not a lowercase word")
    rules = _FILE_RULES[path]
    if path == EVALS:
        _check_eval_cases(text, rules, path)
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


def bump_patch_revision(text: str) -> str:
    """`text` of `lib/agent-plugins.nix` with `patchRevision` one higher."""
    revision, count = _PATCH_REVISION.subn(
        lambda m: f"{m['head']}{int(m['n']) + 1}{m['tail']}", text)
    if count != 1:
        raise CopyError(f"{PLUGINS_NIX}: expected exactly one patchRevision binding, found {count}")
    return revision


def write(root: Path, effort: str = EFFORT) -> list[str]:
    """Rewrite every copy under `root` to carry `effort`; the relative paths that changed.

    Every copy is rendered before any is written. A changed patch also bumps `patchRevision`.
    """
    pending = {}
    for path in _FILE_RULES:
        current = (root / path).read_text(encoding="utf-8")
        wanted = render(path, current, effort)
        if wanted != current:
            pending[path] = wanted
    if PATCH in pending:
        pending[PLUGINS_NIX] = bump_patch_revision(
            (root / PLUGINS_NIX).read_text(encoding="utf-8"))
    for path, wanted in pending.items():
        (root / path).write_text(wanted, encoding="utf-8")
    return list(pending)


def render_skill_dir(directory: Path, effort: str = EFFORT) -> list[str]:
    """Rewrite the skill copies inside an installed skill `directory` to carry `effort`."""
    pending = {}
    for path, inside in SKILL_DIR_FILES.items():
        current = (directory / inside).read_text(encoding="utf-8")
        wanted = render(path, current, effort)
        if wanted != current:
            pending[inside] = wanted
    for inside, wanted in pending.items():
        (directory / inside).write_text(wanted, encoding="utf-8")
    return list(pending)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="codex_review_effort", description=__doc__.split("\n")[0])
    parser.add_argument("--write", action="store_true", help="rewrite the copies from EFFORT")
    parser.add_argument("--root", type=Path, default=None,
                        help="repository root (default: the checkout this module is in)")
    parser.add_argument("--render-skill", type=Path, metavar="DIR",
                        help="rewrite the skill copies inside this skill directory (the build's step)")
    args = parser.parse_args(argv)
    try:
        if args.render_skill:
            render_skill_dir(args.render_skill)
            return 0
        # Resolved here: a store copy of this file has no checkout above it.
        root = args.root or Path(__file__).resolve().parents[3]
        if args.write:
            for path in write(root):
                print(f"rewrote {path} to effort {EFFORT}")
            return 0
        stale = disagreements(root)
    except CopyError as error:
        print(f"codex_review_effort: {error}", file=sys.stderr)
        return 2
    for path in stale:
        print(f"{path} does not carry effort {EFFORT}", file=sys.stderr)
    return 1 if stale else 0


if __name__ == "__main__":
    raise SystemExit(main())
