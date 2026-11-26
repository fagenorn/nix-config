"""Run the agent workflow suite's members a branch touches, or the whole suite after a build when a build input changed (ADR-delivery-012).

Usage: `python -m agent_tools.delivery.touched_tests --base REF [--root DIR]
[--source-root DIR]... [--pair SOURCE=TEST]... [--cover SOURCE_GLOB=MEMBER_GLOB]...
[--suite-file PATH] [--build-when GLOB]... [--build-command CMD] [--env-from MEMBER=CMD]...`

A project's `test-touched` recipe runs this module (it has no command-table row, after
`agent_tools.delivery.verification_command`). It reads no project policy: the base, the
source roots, the pairs, the covers, the globs and the build command are all flags. The members
are those of the `agent-workflow-tests` recipe in `<root>/<suite file>` (`--suite-file`, default
`justfile`), read with
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
- cover: a member matching one of a `--cover` value's member globs, when a changed path
  matches its source glob (`fnmatch`, so `*` also matches `/`). A cover never selects a
  non-member.
- pair: for a changed `--pair` source, each of its tests, even when it is not a member.

Full rule: `full_because` is every changed path, in diff order, matching a `--build-when` glob
(`fnmatch`, so `*` also matches `/`), and the selection is full when it is not empty. A full
selection builds first, after `test-touched: building with <command>: <path> changed` on
stderr (a non-zero build exit is the result with no suite run), then runs every member, then
the pair tests of changed pair sources that are not members. With no match no build runs and
the selection is the rules above. `--build-when` without `--build-command` is a usage error
(exit 2), as is a `--pair` or `--cover` value with no `=` or an empty side.

Environment member: `--env-from MEMBER=CMD` names a test file that needs variables only a
build gives it. When MEMBER is selected, the build command runs first (unless a full
selection already ran it), then CMD runs from the root and prints one `NAME=VALUE` line per
variable (blank lines are skipped; any other line, or a non-zero exit, is the result with no
suite run: the exit code, or 2 for a bad line), and MEMBER runs through the suite runner on its
own with those variables added to the environment. The other selected members run first, as
without the flag, and the result is the first non-zero exit of the runs. `--env-from` without
`--build-command` is a usage error (exit 2), as is a value with no `=` or an empty side, or
the same MEMBER twice.

Selection file: when the environment variable `VERIFIED_TREE_SELECTION` (`SELECTION_ENV`)
names a path, the selection is written there before anything runs, as one line of JSON with
sorted keys: `base`, `changed`, `full`, `full_because` and `selected`, even when nothing is
selected. A file that cannot be written prints `test-touched: cannot write the selection to
<path>: <error>` on stderr and changes no exit code. The build and the suite runner start
without the variable.

Output: when nothing is selected, on stdout `test-touched: no suite member is touched by
<base>...HEAD`, and the result is 0 (or the build's 0). Otherwise, on stderr,
`test-touched: running <n>: <paths>`, and the result is the exit code of
`agent_tools.delivery.suite_runner` run on the selection from the root. A failing
`git diff`, such as an unknown base, prints git's stderr and returns 2.
"""

import argparse
import ast
import fnmatch
import json
import os
import shlex
import subprocess
import sys
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path

from agent_tools.delivery.suite_runner import suite_members


SELECTION_ENV = "VERIFIED_TREE_SELECTION"


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
           pairs: Mapping[str, Sequence[str]] = {},
           covers: Mapping[str, Sequence[str]] = {}) -> list[str]:
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
                or any(fnmatch.fnmatchcase(member, g)
                       for source, globs in covers.items()
                       if any(fnmatch.fnmatchcase(p, source) for p in changed)
                       for g in globs)
                or any(p in text or (Path(p).parent == Path(member).parent
                                     and Path(p).name in text) for p in changed)):
            selected.append(member)
    for source, tests in pairs.items():
        if source in changed:
            selected.extend(t for t in tests if t not in selected)
    return selected


def selection(changed: Sequence[str], members: Sequence[str], read: Callable[[str], str], *,
              source_roots: Sequence[str] = (),
              pairs: Mapping[str, Sequence[str]] = {},
              covers: Mapping[str, Sequence[str]] = {},
              build_globs: Sequence[str] = ()) -> dict:
    full_because = [p for p in changed if any(fnmatch.fnmatchcase(p, g) for g in build_globs)]
    if full_because:
        selected = list(members)
        for source, tests in pairs.items():
            if source in changed:
                selected.extend(t for t in tests if t not in selected)
    else:
        selected = select(changed, members, read, source_roots=source_roots,
                          pairs=pairs, covers=covers)
    return {"changed": list(changed), "full": bool(full_because),
            "full_because": full_because, "selected": selected}


def _parse_mapping(parser: argparse.ArgumentParser, flag: str, shape: str,
                   values: Sequence[str]) -> dict[str, list[str]]:
    mapping: dict[str, list[str]] = {}
    for value in values:
        source, separator, target = value.partition("=")
        if not separator or not source or not target:
            parser.error(f"{flag} {value!r}: expected {shape}")
        mapping.setdefault(source, []).append(target)
    return mapping


def parse_pairs(parser: argparse.ArgumentParser, values: Sequence[str]) -> dict[str, list[str]]:
    return _parse_mapping(parser, "--pair", "SOURCE=TEST", values)


def parse_covers(parser: argparse.ArgumentParser, values: Sequence[str]) -> dict[str, list[str]]:
    return _parse_mapping(parser, "--cover", "SOURCE_GLOB=MEMBER_GLOB", values)


def default_execute(argv: list[str], cwd: Path, extra: Mapping[str, str] | None = None) -> int:
    env = {k: v for k, v in os.environ.items() if k != SELECTION_ENV}
    env.update(extra or {})
    return subprocess.run(argv, cwd=cwd, env=env).returncode


def default_capture(argv: list[str], cwd: Path) -> tuple[int, str]:
    env = {k: v for k, v in os.environ.items() if k != SELECTION_ENV}
    result = subprocess.run(argv, cwd=cwd, env=env, stdout=subprocess.PIPE, text=True)
    return result.returncode, result.stdout


def parse_assignments(output: str) -> dict[str, str]:
    assignments: dict[str, str] = {}
    for line in output.splitlines():
        if not line.strip():
            continue
        name, separator, value = line.partition("=")
        if not separator or not name.isidentifier():
            raise ValueError(f"not a NAME=VALUE line: {line!r}")
        assignments[name] = value
    return assignments


def _say(stream, line: str) -> None:
    print(line, file=stream, flush=True)


def main(argv: Sequence[str] | None = None, *,
         execute: Callable[..., int] | None = None,
         capture: Callable[[list[str], Path], tuple[int, str]] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="touched-tests")
    parser.add_argument("--base", required=True)
    parser.add_argument("--root", default=None)
    parser.add_argument("--source-root", action="append", default=[])
    parser.add_argument("--pair", action="append", default=[])
    parser.add_argument("--cover", action="append", default=[])
    parser.add_argument("--suite-file", default="justfile")
    parser.add_argument("--build-when", action="append", default=[])
    parser.add_argument("--build-command", default=None)
    parser.add_argument("--env-from", action="append", default=[])
    args = parser.parse_args(argv)
    pairs = parse_pairs(parser, args.pair)
    covers = parse_covers(parser, args.cover)
    if args.build_when and not args.build_command:
        parser.error("--build-when needs --build-command")
    env_commands = _parse_mapping(parser, "--env-from", "MEMBER=CMD", args.env_from)
    if env_commands and not args.build_command:
        parser.error("--env-from needs --build-command")
    for member, commands in env_commands.items():
        if len(commands) > 1:
            parser.error(f"--env-from names {member!r} twice")
    run = execute or default_execute
    capture_output = capture or default_capture
    root = Path(args.root) if args.root else Path.cwd()
    try:
        changed = changed_paths(root, args.base)
    except GitError as error:
        _say(sys.stderr, str(error))
        return 2

    def read(path: str) -> str:
        try:
            return (root / path).read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            return ""

    members = suite_members(read(args.suite_file))
    chosen = selection(changed, members, read, source_roots=args.source_root, pairs=pairs,
                       covers=covers, build_globs=args.build_when)
    target = os.environ.get(SELECTION_ENV)
    if target:
        document = json.dumps({"base": args.base, **chosen}, sort_keys=True,
                              separators=(",", ":")) + "\n"
        try:
            Path(target).write_text(document, encoding="utf-8")
        except OSError as error:
            _say(sys.stderr, f"test-touched: cannot write the selection to {target}: {error}")

    built = chosen["full"]
    if built:
        _say(sys.stderr, f"test-touched: building with {args.build_command}: "
                         f"{chosen['full_because'][0]} changed")
        code = run(shlex.split(args.build_command), root)
        if code != 0:
            return code
    selected = chosen["selected"]
    if not selected:
        _say(sys.stdout, f"test-touched: no suite member is touched by {args.base}...HEAD")
        return 0
    prepared: dict[str, dict[str, str]] = {}
    for member in selected:
        if member not in env_commands:
            continue
        if not built:
            _say(sys.stderr, f"test-touched: building with {args.build_command}: "
                             f"{member} needs its build environment")
            code = run(shlex.split(args.build_command), root)
            if code != 0:
                return code
            built = True
        code, output = capture_output(shlex.split(env_commands[member][0]), root)
        if code != 0:
            return code
        try:
            prepared[member] = parse_assignments(output)
        except ValueError as error:
            _say(sys.stderr, f"test-touched: {env_commands[member][0]}: {error}")
            return 2
    _say(sys.stderr, f"test-touched: running {len(selected)}: {' '.join(selected)}")
    runner = [sys.executable, "-m", "agent_tools.delivery.suite_runner"]
    plain = [m for m in selected if m not in prepared]
    results = [run([*runner, *plain], root)] if plain else []
    results.extend(run([*runner, member], root, prepared[member]) for member in selected
                   if member in prepared)
    return next((code for code in results if code != 0), 0)


if __name__ == "__main__":
    sys.exit(main())
