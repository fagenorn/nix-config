"""Run the agent workflow suite's members a branch touches, after a build when a build input changed (ADR-delivery-012).

Usage: `python -m agent_tools.delivery.touched_tests --base REF [--root DIR]
[--source-root DIR]... [--pair SOURCE=TEST]... [--build-when GLOB]... [--build-command CMD]`

A project's `test-touched` recipe runs this module (it has no command-table row, after
`agent_tools.delivery.verification_command`). It reads no project policy: the base, the
source roots, the pairs, the globs and the build command are all flags. The members are those
of the `agent-workflow-tests` recipe in `<root>/justfile`, read with
`agent_tools.delivery.suite_runner.suite_members`. The changed paths are the lines of
`git diff --no-renames --name-only <base>...HEAD`, read from `<root>`.

Selection rules, in member order, then the pair tests in flag order, with no duplicates.
Apart from the pairs, only members are selected, so a nightly or unregistered test never is.

- touched: a changed path that is a member.
- named: for a changed `<dir>/<stem>.py` whose name does not start with `test_`, every member
  named `test_<stem>.py` or starting with `test_<stem>_`.
- importer: for a changed `.py` under a source root, the module is its path relative to the
  root with `/` turned into `.` and `.py` (or `/__init__.py`) dropped. A member is selected
  when its parsed source holds `import M`, `from M import ...` or `from P import name` where
  `P.name` is `M`. Submodules of `M`, a textual prefix, and a mention in a comment or a
  string do not count. A member that does not parse is skipped.
- path: a member whose text holds the changed path, or a member in the same directory whose
  text holds the changed path's file name.
- pair: for a changed `--pair` source, each of its tests, even when it is not a member.

Build rule: when a changed path matches a `--build-when` glob (`fnmatch`, so `*` also matches
`/`), the build command runs first, after `test-touched: building with <command>: <path>
changed` on stderr, and a non-zero build exit is the result with no suite run. With no match
no build runs. `--build-when` without `--build-command` is a usage error (exit 2), as is a
`--pair` value with no `=`.

Output: when nothing is selected, on stdout `test-touched: no suite member is touched by
<base>...HEAD`, and the result is 0 (or the build's 0). Otherwise, on stderr,
`test-touched: running <n>: <paths>`, and the result is the exit code of
`agent_tools.delivery.suite_runner` run on the selection from the root. A failing
`git diff`, such as an unknown base, prints git's stderr and returns 2.
"""

import argparse
import ast
import fnmatch
import shlex
import subprocess
import sys
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path

from agent_tools.delivery.suite_runner import suite_members


class GitError(RuntimeError):
    pass


def changed_paths(root: Path, base: str) -> list[str]:
    result = subprocess.run(
        ["git", "-C", str(root), "diff", "--no-renames", "--name-only", f"{base}...HEAD"],
        capture_output=True, text=True)
    if result.returncode != 0:
        raise GitError(result.stderr.rstrip("\n"))
    return result.stdout.splitlines()


def build_trigger(changed: Sequence[str], globs: Sequence[str]) -> str | None:
    for path in changed:
        if any(fnmatch.fnmatchcase(path, glob) for glob in globs):
            return path
    return None


def module_name(path: str, source_roots: Sequence[str]) -> str | None:
    for root in source_roots:
        prefix = root.rstrip("/") + "/"
        if not path.startswith(prefix) or not path.endswith(".py"):
            continue
        parts = path[len(prefix):-len(".py")].split("/")
        if parts[-1] == "__init__":
            parts = parts[:-1]
        if parts:
            return ".".join(parts)
    return None


def imports_module(text: str, module: str) -> bool:
    try:
        tree = ast.parse(text)
    except (SyntaxError, ValueError):
        return False
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            if any(alias.name == module for alias in node.names):
                return True
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            if node.module == module:
                return True
            if any(f"{node.module}.{alias.name}" == module for alias in node.names):
                return True
    return False


def select(changed: Sequence[str], members: Sequence[str], read: Callable[[str], str], *,
           source_roots: Sequence[str] = (),
           pairs: Mapping[str, Sequence[str]] = {}) -> list[str]:
    modules = [m for m in (module_name(p, source_roots) for p in changed) if m]
    stems = [Path(p).stem for p in changed
             if p.endswith(".py") and not Path(p).name.startswith("test_")]
    selected: list[str] = []
    for member in members:
        name = Path(member).name
        text = read(member)
        if (member in changed
                or any(name == f"test_{s}.py" or name.startswith(f"test_{s}_") for s in stems)
                or any(imports_module(text, m) for m in modules)
                or any(p in text or (Path(p).parent == Path(member).parent
                                     and Path(p).name in text) for p in changed)):
            selected.append(member)
    for source, tests in pairs.items():
        if source in changed:
            selected.extend(t for t in tests if t not in selected)
    return selected


def parse_pairs(parser: argparse.ArgumentParser, values: Sequence[str]) -> dict[str, list[str]]:
    pairs: dict[str, list[str]] = {}
    for value in values:
        source, separator, test = value.partition("=")
        if not separator or not source or not test:
            parser.error(f"--pair {value!r}: expected SOURCE=TEST")
        pairs.setdefault(source, []).append(test)
    return pairs


def default_execute(argv: list[str], cwd: Path) -> int:
    return subprocess.run(argv, cwd=cwd).returncode


def _say(stream, line: str) -> None:
    print(line, file=stream, flush=True)


def main(argv: Sequence[str] | None = None, *,
         execute: Callable[[list[str], Path], int] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="touched-tests")
    parser.add_argument("--base", required=True)
    parser.add_argument("--root", default=None)
    parser.add_argument("--source-root", action="append", default=[])
    parser.add_argument("--pair", action="append", default=[])
    parser.add_argument("--build-when", action="append", default=[])
    parser.add_argument("--build-command", default=None)
    args = parser.parse_args(argv)
    pairs = parse_pairs(parser, args.pair)
    if args.build_when and not args.build_command:
        parser.error("--build-when needs --build-command")
    run = execute or default_execute
    root = Path(args.root) if args.root else Path.cwd()
    try:
        changed = changed_paths(root, args.base)
    except GitError as error:
        _say(sys.stderr, str(error))
        return 2

    code = 0
    trigger = build_trigger(changed, args.build_when)
    if trigger is not None:
        _say(sys.stderr, f"test-touched: building with {args.build_command}: {trigger} changed")
        code = run(shlex.split(args.build_command), root)
        if code != 0:
            return code

    def read(path: str) -> str:
        try:
            return (root / path).read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            return ""

    members = suite_members(read("justfile"))
    selected = select(changed, members, read, source_roots=args.source_root, pairs=pairs)
    if not selected:
        _say(sys.stdout, f"test-touched: no suite member is touched by {args.base}...HEAD")
        return code
    _say(sys.stderr, f"test-touched: running {len(selected)}: {' '.join(selected)}")
    return run([sys.executable, "-m", "agent_tools.delivery.suite_runner", *selected], root)


if __name__ == "__main__":
    sys.exit(main())
